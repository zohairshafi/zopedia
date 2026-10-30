import Foundation

public struct WikiEnvVariable: Decodable, Identifiable, Hashable, Sendable {
    public let name: String
    public let kind: String
    public let description: String
    public let defaultValue: String
    public let currentValue: String
    public let source: String
    public let hasOverride: Bool
    public let overrideValue: String?
    public let minimum: Double?
    public let maximum: Double?

    public var id: String { name }

    public var isOverridden: Bool { hasOverride }

    enum CodingKeys: String, CodingKey {
        case name
        case kind
        case description
        case defaultValue = "default_value"
        case currentValue = "current_value"
        case source
        case hasOverride = "has_override"
        case overrideValue = "override_value"
        case minimum
        case maximum
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decodeIfPresent(String.self, forKey: .name) ?? ""
        kind = try container.decodeIfPresent(String.self, forKey: .kind) ?? "string"
        description = try container.decodeIfPresent(String.self, forKey: .description) ?? ""
        defaultValue = try container.decodeIfPresent(String.self, forKey: .defaultValue) ?? ""
        currentValue = try container.decodeIfPresent(String.self, forKey: .currentValue) ?? ""
        source = try container.decodeIfPresent(String.self, forKey: .source) ?? "default"
        hasOverride = try container.decodeIfPresent(Bool.self, forKey: .hasOverride) ?? false
        overrideValue = try container.decodeIfPresent(String.self, forKey: .overrideValue)
        minimum = try container.decodeIfPresent(Double.self, forKey: .minimum)
        maximum = try container.decodeIfPresent(Double.self, forKey: .maximum)
    }
}

public struct WikiEnvConfig: Decodable, Sendable {
    public let status: String
    public let variables: [WikiEnvVariable]
    public let overridesFile: String
    public let restartSupported: Bool

    enum CodingKeys: String, CodingKey {
        case status
        case variables
        case overridesFile = "overrides_file"
        case restartSupported = "restart_supported"
    }
}

public struct WikiEnvSetResponse: Decodable, Sendable {
    public let status: String
    public let updated: [String]
    public let cleared: [String]
    public let invalid: [String: String]
    public let overridesFile: String
    public let restartSupported: Bool
    public let restartScheduled: Bool

    enum CodingKeys: String, CodingKey {
        case status
        case updated
        case cleared
        case invalid
        case overridesFile = "overrides_file"
        case restartSupported = "restart_supported"
        case restartScheduled = "restart_scheduled"
    }
}

/// `nil` values clear an override and fall back to the default.
public struct WikiEnvSetRequest: Encodable, Sendable {
    public let values: [String: String?]
    public let restartBackend: Bool

    public init(values: [String: String?], restartBackend: Bool) {
        self.values = values
        self.restartBackend = restartBackend
    }

    enum CodingKeys: String, CodingKey {
        case values
        case restartBackend = "restart_backend"
    }

    private struct DynamicKey: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { nil }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: DynamicKey.self)
        try container.encode(restartBackend, forKey: DynamicKey(stringValue: "restart_backend"))

        var valuesContainer = container.nestedContainer(
            keyedBy: DynamicKey.self,
            forKey: DynamicKey(stringValue: "values")
        )
        for (name, value) in values {
            let key = DynamicKey(stringValue: name)
            if let value {
                try valuesContainer.encode(value, forKey: key)
            } else {
                try valuesContainer.encodeNil(forKey: key)
            }
        }
    }
}
