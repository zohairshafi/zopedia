import XCTest
@testable import ZopediaKit

final class ServiceModelTests: XCTestCase {
    private let decoder = JSONDecoder.zopedia

    func testMaintenanceScheduleDecodesSQLiteFlags() throws {
        let json = #"""
        {"schedules":[{"id":"s1","enabled":1,"interval_type":"daily",
          "with_web_fill":0,"run_hour":3,"run_dow":null,"run_dom":null,
          "created_at":"2026-10-30T12:00:00+00:00","last_run_at":null,
          "next_run_at":"2026-10-31T03:00:00+00:00"}]}
        """#
        let response = try decoder.decode(
            MaintenanceScheduleListResponse.self, from: Data(json.utf8)
        )
        XCTAssertEqual(response.schedules.count, 1)
        XCTAssertEqual(response.schedules[0].intervalType, "daily")
        XCTAssertTrue(response.schedules[0].enabled)
        XCTAssertFalse(response.schedules[0].withWebFill)
        XCTAssertEqual(response.schedules[0].runHour, 3)
        XCTAssertNotNil(response.schedules[0].nextRunAt)
    }

    func testPeriodicSummaryDecodes() throws {
        let json = #"""
        {"configs":[{"id":"p1","topic":"oil","interval_type":"weekly",
          "enabled":true,"run_hour":9,"run_dow":0,"run_dom":null,
          "last_run_at":null,"next_run_at":"2026-11-02T09:00:00Z",
          "created_at":"2026-10-30T12:00:00.123456+00:00",
          "trusted_count":2,"rounds":3,"sources_per_round":10}]}
        """#
        let response = try decoder.decode(
            PeriodicResearchListResponse.self, from: Data(json.utf8)
        )
        let config = try XCTUnwrap(response.configs.first)
        XCTAssertEqual(config.topic, "oil")
        XCTAssertEqual(config.intervalType, "weekly")
        XCTAssertEqual(config.runDow, 0)
        XCTAssertEqual(config.trustedCount, 2)
        XCTAssertNotNil(config.nextRunAt)
        XCTAssertNotNil(config.createdAt)
    }

    func testWikiEnvDecodes() throws {
        let json = #"""
        {"status":"ok","variables":[{"name":"ZOPEDIA_WIKI_WATCHER",
          "kind":"bool","description":"Watch","default_value":"true",
          "current_value":"false","source":"environment","has_override":true,
          "override_value":"false","minimum":null,"maximum":null}],
          "overrides_file":"/tmp/overrides.json","restart_supported":true}
        """#
        let config = try decoder.decode(WikiEnvConfig.self, from: Data(json.utf8))
        let variable = try XCTUnwrap(config.variables.first)
        XCTAssertEqual(variable.kind, "bool")
        XCTAssertTrue(variable.hasOverride)
        XCTAssertEqual(variable.overrideValue, "false")
        XCTAssertTrue(config.restartSupported)
    }

    func testWikiEnvSetEncodesNullsForClearedOverrides() throws {
        let request = WikiEnvSetRequest(
            values: ["ZOPEDIA_WIKI_WATCHER": "true", "ZOPEDIA_RAG_ENABLED": nil],
            restartBackend: true
        )
        let data = try JSONEncoder().encode(request)
        let object = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        let values = try XCTUnwrap(object["values"] as? [String: Any])
        XCTAssertEqual(values["ZOPEDIA_WIKI_WATCHER"] as? String, "true")
        XCTAssertTrue(values["ZOPEDIA_RAG_ENABLED"] is NSNull)
        XCTAssertEqual(object["restart_backend"] as? Bool, true)
    }

    func testPendingApprovalsDecode() throws {
        let json = #"""
        {"approvals":[{"id":"a1","source":"research","config_id":"p1",
          "thread_id":"t1","order":{"side":"buy","symbol":"AAPL","qty":2,
          "type":"market"},"rationale":"because","status":"pending",
          "created_at":"2026-10-30T12:00:00+00:00",
          "expires_at":"2026-10-30T12:30:00+00:00","decided_at":null,
          "result":null}],"pending_count":1}
        """#
        let response = try decoder.decode(
            PendingApprovalsResponse.self, from: Data(json.utf8)
        )
        let approval = try XCTUnwrap(response.approvals.first)
        XCTAssertEqual(response.pendingCount, 1)
        XCTAssertEqual(approval.side, "BUY")
        XCTAssertEqual(approval.symbol, "AAPL")
        XCTAssertEqual(approval.quantity, "2")
        XCTAssertNotNil(approval.expiresAt)
    }

    func testResearchConfigEncoding() throws {
        let config = ResearchConfig(
            topic: "oil",
            rounds: 2,
            sourcesPerRound: 5,
            autoMode: true,
            timelimit: "all",
            sessionID: "s1"
        )
        let data = try JSONEncoder().encode(config)
        let object = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(object["topic"] as? String, "oil")
        XCTAssertEqual(object["sources_per_round"] as? Int, 5)
        XCTAssertEqual(object["timelimit"] as? String, "")
        XCTAssertEqual(object["session_id"] as? String, "s1")
        XCTAssertEqual(object["auto_mode"] as? Bool, true)
    }
}
