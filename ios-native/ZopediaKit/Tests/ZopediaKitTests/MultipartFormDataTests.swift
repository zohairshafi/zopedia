import XCTest
@testable import ZopediaKit

final class MultipartFormDataTests: XCTestCase {
    func testExactBytesForMultipleParts() throws {
        let body = try MultipartFormData.write(
            parts: [
                MultipartPart(
                    fieldName: "files",
                    filename: "a.txt",
                    mimeType: "text/plain",
                    data: Data("hello".utf8)
                ),
                MultipartPart(
                    fieldName: "files",
                    filename: "b.bin",
                    mimeType: "application/octet-stream",
                    data: Data([0, 1, 2])
                ),
            ],
            boundary: "TESTBOUNDARY"
        )
        defer { try? FileManager.default.removeItem(at: body.fileURL) }

        var expected = Data()
        expected.append(Data("--TESTBOUNDARY\r\n".utf8))
        expected.append(Data("Content-Disposition: form-data; name=\"files\"; filename=\"a.txt\"\r\n".utf8))
        expected.append(Data("Content-Type: text/plain\r\n\r\n".utf8))
        expected.append(Data("hello".utf8))
        expected.append(Data("\r\n".utf8))
        expected.append(Data("--TESTBOUNDARY\r\n".utf8))
        expected.append(Data("Content-Disposition: form-data; name=\"files\"; filename=\"b.bin\"\r\n".utf8))
        expected.append(Data("Content-Type: application/octet-stream\r\n\r\n".utf8))
        expected.append(Data([0, 1, 2]))
        expected.append(Data("\r\n".utf8))
        expected.append(Data("--TESTBOUNDARY--\r\n".utf8))

        XCTAssertEqual(try Data(contentsOf: body.fileURL), expected)
        XCTAssertEqual(body.contentType, "multipart/form-data; boundary=TESTBOUNDARY")
    }

    func testFilenameEscaping() {
        XCTAssertEqual(MultipartFormData.escape("dir/sub/../../evil\"name\n.txt"), "evil\\\"name .txt")
        XCTAssertEqual(MultipartFormData.escape("plain.txt"), "plain.txt")
    }
}
