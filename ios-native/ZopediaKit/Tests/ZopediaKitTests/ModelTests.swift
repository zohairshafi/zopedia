import XCTest
@testable import ZopediaKit

final class ModelTests: XCTestCase {
    func testTokenResponseDecoding() throws {
        let json = #"""
        {
          "access_token": "a",
          "refresh_token": "r",
          "must_change_password": true,
          "permissions": {
            "can_save_chat_history": true,
            "can_upload_files": false,
            "is_admin": true
          }
        }
        """#
        let response = try JSONDecoder().decode(TokenResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.accessToken, "a")
        XCTAssertEqual(response.refreshToken, "r")
        XCTAssertTrue(response.mustChangePassword)
        XCTAssertEqual(
            response.permissions,
            Permissions(canSaveChatHistory: true, canUploadFiles: false, isAdmin: true)
        )
    }

    func testMissingPermissionsDefaultToFalse() throws {
        let json = #"{"access_token":"a","refresh_token":"r","must_change_password":false}"#
        let response = try JSONDecoder().decode(TokenResponse.self, from: Data(json.utf8))
        XCTAssertNil(response.permissions)
        XCTAssertFalse(response.mustChangePassword)
    }

    func testAuthStatusDecoding() throws {
        let json = #"{"initialized":true,"requires_password_change":false,"auth_disabled":true}"#
        let status = try JSONDecoder().decode(AuthStatus.self, from: Data(json.utf8))
        XCTAssertTrue(status.initialized)
        XCTAssertFalse(status.requiresPasswordChange)
        XCTAssertTrue(status.authDisabled)
    }

    func testJSONValueRoundTrip() throws {
        let value = JSONValue.object([
            "a": .int(1),
            "b": .string("x"),
            "c": .array([.bool(true), .null]),
        ])
        let data = try JSONEncoder().encode(value)
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: data), value)
    }

    func testJSONValueFromAny() throws {
        let value = try JSONValue(any: [
            "n": 1.5,
            "i": 2,
            "b": true,
            "s": "x",
        ] as [String: Any])
        XCTAssertEqual(value.objectValue?["i"], .int(2))
        XCTAssertEqual(value.objectValue?["n"], .double(1.5))
        XCTAssertEqual(value.objectValue?["b"], .bool(true))
        XCTAssertEqual(value.objectValue?["s"], .string("x"))
    }
}
