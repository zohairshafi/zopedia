import XCTest
@testable import ZopediaKit

final class ResearchStreamDecoderTests: XCTestCase {
    func testDone() throws {
        XCTAssertEqual(try ResearchStreamDecoder.decode("[DONE]"), .done)
    }

    func testStarted() throws {
        let event = try ResearchStreamDecoder.decode(#"""
        {"type":"research_started","topic":"oil","total_rounds":3,
         "sources_per_round":10,"auto_mode":true}
        """#)
        XCTAssertEqual(
            event,
            .started(topic: "oil", totalRounds: 3, sourcesPerRound: 10, autoMode: true)
        )
    }

    func testSourcesFound() throws {
        let event = try ResearchStreamDecoder.decode(#"""
        {"type":"research_sources_found","round":1,"sources":[
          {"url":"https://a.example/x","title":"A","snippet":"s",
           "source_type":"webpage","is_trusted":true,"relevance":0.5,
           "already_in_wiki":false}
        ]}
        """#)

        guard case .sourcesFound(let round, let sources) = event else {
            return XCTFail("expected sourcesFound")
        }
        XCTAssertEqual(round, 1)
        XCTAssertEqual(sources.count, 1)
        XCTAssertEqual(sources[0].url, "https://a.example/x")
        XCTAssertTrue(sources[0].isTrusted)
        XCTAssertFalse(sources[0].alreadyInWiki)
    }

    func testAwaitingApprovalAndRoundComplete() throws {
        let approval = try ResearchStreamDecoder.decode(
            #"{"type":"research_awaiting_approval","round":2,"source_count":7}"#
        )
        XCTAssertEqual(approval, .awaitingApproval(round: 2, sourceCount: 7))

        let complete = try ResearchStreamDecoder.decode(#"""
        {"type":"research_round_complete","round":2,"sources_ingested":3,
         "sources_failed":1,"new_pages":["a"],"failed_pages":["b"]}
        """#)
        XCTAssertEqual(
            complete,
            .roundComplete(
                round: 2, ingested: 3, failed: 1,
                newPages: ["a"], failedPages: ["b"]
            )
        )
    }

    func testMaintenanceCompleteReadsNestedSummary() throws {
        let event = try ResearchStreamDecoder.decode(#"""
        {"type":"research_maintenance_complete","summary":{"steps_completed":4}}
        """#)
        XCTAssertEqual(event, .maintenanceComplete(stepsCompleted: 4))
    }

    func testToolStatusPrefersText() throws {
        let event = try ResearchStreamDecoder.decode(
            #"{"type":"research_tool_status","text":"Generating title..."}"#
        )
        XCTAssertEqual(event, .toolStatus("Generating title..."))
    }

    func testUnknownTypeIsNotAnError() throws {
        let event = try ResearchStreamDecoder.decode(
            #"{"type":"research_future_event","value":1}"#
        )
        XCTAssertEqual(event, .unknown(type: "research_future_event"))
    }

    func testMalformedFrameThrows() {
        XCTAssertThrowsError(try ResearchStreamDecoder.decode("not json"))
        XCTAssertThrowsError(try ResearchStreamDecoder.decode(#"{"no":"type"}"#))
    }
}
