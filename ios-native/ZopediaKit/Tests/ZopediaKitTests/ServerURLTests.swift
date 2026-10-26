import XCTest
@testable import ZopediaKit

final class ServerURLTests: XCTestCase {
    func testHTTPIPIsAllowed() throws {
        let url = try ServerURL.normalize("http://192.168.2.23:8080")
        XCTAssertEqual(url.absoluteString, "http://192.168.2.23:8080")
    }

    func testHTTPLocalNameIsAllowed() throws {
        XCTAssertNoThrow(try ServerURL.normalize("http://zohairs-macbook-home.local:8080"))
        XCTAssertNoThrow(try ServerURL.normalize("http://localhost:8000"))
        XCTAssertNoThrow(try ServerURL.normalize("http://myserver:8000"))
    }

    func testPublicHTTPIsRejected() {
        XCTAssertThrowsError(try ServerURL.normalize("http://homenet-bos.asuscomm.com"))
    }

    func testHTTPSPublicIsAllowed() throws {
        let url = try ServerURL.normalize("https://homenet-bos.asuscomm.com/")
        XCTAssertEqual(url.absoluteString, "https://homenet-bos.asuscomm.com")
    }

    func testTrailingSlashesAreStripped() throws {
        let url = try ServerURL.normalize("http://192.168.2.23:8000///")
        XCTAssertEqual(url.absoluteString, "http://192.168.2.23:8000")
    }

    func testInvalidSchemeIsRejected() {
        XCTAssertThrowsError(try ServerURL.normalize("ftp://example.com"))
        XCTAssertThrowsError(try ServerURL.normalize("not a url"))
    }
}
