import Foundation

public struct APIRequest: Sendable {
    public var method: String
    public var path: String
    public var query: [URLQueryItem]
    public var body: Data?
    public var contentType: String?
    public var requiresAuth: Bool
    /// Overrides the default 60 s request timeout.
    public var timeout: TimeInterval?

    public init(
        method: String = "GET",
        path: String,
        query: [URLQueryItem] = [],
        body: Data? = nil,
        contentType: String? = nil,
        requiresAuth: Bool = true,
        timeout: TimeInterval? = nil
    ) {
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.contentType = contentType
        self.requiresAuth = requiresAuth
        self.timeout = timeout
    }
}

public actor APIClient {
    public let baseURL: URL
    public let auth: AuthSession
    private let session: URLSession

    public init(baseURL: URL, auth: AuthSession, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.auth = auth
        self.session = session
    }

    public func send(_ request: APIRequest) async throws -> Data {
        var didRetry = false
        while true {
            var urlRequest = try makeRequest(request)
            if request.requiresAuth, let token = await auth.accessToken {
                urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }

            let data: Data
            let response: URLResponse
            do {
                (data, response) = try await session.data(for: urlRequest)
            } catch let error as URLError where error.code == .cancelled {
                throw APIError.cancelled
            } catch {
                throw APIError.transport(error.localizedDescription)
            }

            guard let http = response as? HTTPURLResponse else {
                throw APIError.transport("The server returned a non-HTTP response.")
            }

            if http.statusCode == 401, request.requiresAuth, !didRetry {
                _ = try await auth.refreshIfNeeded()
                didRetry = true
                continue
            }

            try validate(http, data: data)
            return data
        }
    }

    public func get<Response: Decodable>(
        _ path: String,
        query: [URLQueryItem] = [],
        requiresAuth: Bool = true
    ) async throws -> Response {
        let data = try await send(
            APIRequest(method: "GET", path: path, query: query, requiresAuth: requiresAuth)
        )
        return try decode(data)
    }

    public func request<Body: Encodable, Response: Decodable>(
        method: String,
        path: String,
        body: Body,
        requiresAuth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> Response {
        let encoded = try JSONEncoder().encode(body)
        let data = try await send(
            APIRequest(
                method: method,
                path: path,
                body: encoded,
                contentType: "application/json",
                requiresAuth: requiresAuth,
                timeout: timeout
            )
        )
        return try decode(data)
    }

    public func post<Body: Encodable, Response: Decodable>(
        _ path: String,
        body: Body,
        requiresAuth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> Response {
        try await request(
            method: "POST",
            path: path,
            body: body,
            requiresAuth: requiresAuth,
            timeout: timeout
        )
    }

    /// POST with no body. `timeout` is for actions that block server-side.
    public func post<Response: Decodable>(
        _ path: String,
        timeout: TimeInterval? = nil
    ) async throws -> Response {
        let data = try await send(
            APIRequest(method: "POST", path: path, timeout: timeout)
        )
        return try decode(data)
    }

    public func patch<Body: Encodable, Response: Decodable>(
        _ path: String,
        body: Body
    ) async throws -> Response {
        try await request(method: "PATCH", path: path, body: body)
    }

    public func delete<Response: Decodable>(_ path: String) async throws -> Response {
        let data = try await send(APIRequest(method: "DELETE", path: path))
        return try decode(data)
    }

    /// Upload a file-backed multipart body. The temp file is removed afterwards
    /// and can be re-read for the single 401 retry.
    public func upload<Response: Decodable>(
        _ path: String,
        body: MultipartBody,
        requiresAuth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> Response {
        defer { try? FileManager.default.removeItem(at: body.fileURL) }

        let data = try await sendUpload(
            APIRequest(
                method: "POST",
                path: path,
                contentType: body.contentType,
                requiresAuth: requiresAuth,
                timeout: timeout
            ),
            fromFile: body.fileURL
        )
        return try decode(data)
    }

    private func sendUpload(_ request: APIRequest, fromFile fileURL: URL) async throws -> Data {
        var didRetry = false
        while true {
            var urlRequest = try makeRequest(request)
            if request.requiresAuth, let token = await auth.accessToken {
                urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }

            let data: Data
            let response: URLResponse
            do {
                (data, response) = try await session.upload(for: urlRequest, fromFile: fileURL)
            } catch let error as URLError where error.code == .cancelled {
                throw APIError.cancelled
            } catch {
                throw APIError.transport(error.localizedDescription)
            }

            guard let http = response as? HTTPURLResponse else {
                throw APIError.transport("The server returned a non-HTTP response.")
            }
            if http.statusCode == 401, request.requiresAuth, !didRetry {
                _ = try await auth.refreshIfNeeded()
                didRetry = true
                continue
            }
            try validate(http, data: data)
            return data
        }
    }

    /// Stream `data:` payloads from an SSE endpoint. A 401 triggers one refresh
    /// and a retry. `[DONE]` is yielded to the caller before the stream ends.
    public func streamSSEPayloads(
        _ request: APIRequest,
        timeout: TimeInterval = 600
    ) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var didRetry = false
                while true {
                    do {
                        var urlRequest = try makeRequest(request)
                        urlRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                        urlRequest.timeoutInterval = timeout
                        if request.requiresAuth, let token = await auth.accessToken {
                            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                        }

                        let (bytes, response) = try await session.bytes(for: urlRequest)
                        guard let http = response as? HTTPURLResponse else {
                            throw APIError.transport("The server returned a non-HTTP response.")
                        }

                        if http.statusCode == 401, request.requiresAuth, !didRetry {
                            _ = try await auth.refreshIfNeeded()
                            didRetry = true
                            continue
                        }

                        guard (200..<300).contains(http.statusCode) else {
                            var body = Data()
                            for try await byte in bytes { body.append(byte) }
                            throw error(for: http, data: body)
                        }

                        // AsyncLineSequence drops empty lines, so the SSE blank-line
                        // delimiter never arrives. This server emits exactly one
                        // `data:` line per event, so decode line by line. Multi-line
                        // `data:` payloads would fail loudly rather than silently merge.
                        var sawDone = false
                        for try await line in bytes.lines {
                            guard let payload = SSEParser.dataPayload(from: line) else { continue }
                            continuation.yield(payload)
                            if payload == "[DONE]" {
                                sawDone = true
                                break
                            }
                        }
                        guard sawDone else { throw APIError.streamLost }
                        continuation.finish()
                        return
                    } catch is CancellationError {
                        continuation.finish(throwing: APIError.cancelled)
                        return
                    } catch let error as URLError where error.code == .cancelled {
                        continuation.finish(throwing: APIError.cancelled)
                        return
                    } catch let error as APIError {
                        continuation.finish(throwing: error)
                        return
                    } catch {
                        continuation.finish(throwing: APIError.transport(error.localizedDescription))
                        return
                    }
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Stream chat events.
    public func streamChat(_ chat: ChatRequest) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        let body: Data
        do {
            body = try JSONEncoder().encode(chat)
        } catch {
            return AsyncThrowingStream { continuation in
                continuation.finish(throwing: APIError.decoding("Could not encode the chat request."))
            }
        }

        let payloads = streamSSEPayloads(
            APIRequest(
                method: "POST",
                path: "v1/chat/completions",
                body: body,
                contentType: "application/json"
            ),
            timeout: 600
        )

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    for try await payload in payloads {
                        guard let event = try ChatStreamDecoder.decode(payload) else { continue }
                        continuation.yield(event)
                        if event == .done { break }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private func makeRequest(_ request: APIRequest) throws -> URLRequest {
        guard let url = baseURL.zopediaURL(path: request.path, query: request.query) else {
            throw APIError.invalidURL
        }
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = request.method
        urlRequest.timeoutInterval = request.timeout ?? 60
        if let contentType = request.contentType {
            urlRequest.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        urlRequest.httpBody = request.body
        return urlRequest
    }

    private func validate(_ http: HTTPURLResponse, data: Data) throws {
        guard (200..<300).contains(http.statusCode) else {
            throw error(for: http, data: data)
        }
    }

    private nonisolated func error(for http: HTTPURLResponse, data: Data) -> APIError {
        let detail = HTTPErrorDetail.from(data) ?? "HTTP \(http.statusCode)"
        switch http.statusCode {
        case 401:
            return .unauthorized
        case 403 where detail == "Password change required":
            return .passwordChangeRequired
        case 409:
            return .conflict(detail)
        default:
            return .http(status: http.statusCode, detail: detail)
        }
    }

    private nonisolated func decode<Response: Decodable>(_ data: Data) throws -> Response {
        do {
            return try JSONDecoder.zopedia.decode(Response.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }
}
