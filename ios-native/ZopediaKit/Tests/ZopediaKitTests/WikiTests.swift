import XCTest
@testable import ZopediaKit

final class WikiTests: XCTestCase {
    func testWikiLinkBecomesAppLink() {
        let output = WikiLinkPreprocessor.preprocess("See [[Oil prices]].")
        XCTAssertEqual(
            output,
            "See [Oil prices](zopedia://wiki?path=oil-prices.md)."
        )
    }

    func testWikiLinkWithPathKeepsPath() {
        let output = WikiLinkPreprocessor.preprocess("[[concepts/inflation]]")
        XCTAssertEqual(
            output,
            "[concepts/inflation](zopedia://wiki?path=concepts/inflation.md)"
        )
    }

    func testPlainMarkdownPathBecomesLink() {
        let output = WikiLinkPreprocessor.preprocess("Read concepts/inflation.md now")
        XCTAssertTrue(output.contains("(zopedia://wiki?path=concepts/inflation.md)"))
    }

    func testAnalysisPathGetsMarkdownExtension() {
        let output = WikiLinkPreprocessor.preprocess(
            "analysis/2026-05-01-10-00-oil-prices"
        )
        XCTAssertTrue(
            output.contains("path=analysis/2026-05-01-10-00-oil-prices.md")
        )
    }

    func testCodeSpanIsNotConverted() {
        let input = "`concepts/inflation.md`"
        XCTAssertEqual(WikiLinkPreprocessor.preprocess(input), input)
    }

    func testPagePathFromAppLink() throws {
        let url = try XCTUnwrap(URL(string: "zopedia://wiki?path=concepts%2Finflation.md"))
        XCTAssertEqual(
            WikiLinkPreprocessor.pagePath(from: url),
            "concepts/inflation.md"
        )
        XCTAssertNil(WikiLinkPreprocessor.pagePath(from: URL(string: "https://example.com")!))
    }

    func testFrontmatterIsStripped() {
        let input = "---\ntitle: X\ntags: [a]\n---\n# Heading\nBody"
        XCTAssertEqual(
            WikiLinkPreprocessor.stripFrontmatter(input),
            "# Heading\nBody"
        )
    }

    func testNoFrontmatterIsUnchanged() {
        XCTAssertEqual(
            WikiLinkPreprocessor.stripFrontmatter("# Heading"),
            "# Heading"
        )
    }

    func testWikiFilesDecoding() throws {
        let json = #"""
        {
          "directories": {
            "concepts": {
              "count": 1,
              "files": [{
                "name": "inflation.md",
                "relative_path": "concepts/inflation.md",
                "size": 120,
                "modified": 1793000000.5,
                "preview": "Inflation is..."
              }]
            }
          },
          "root_files": [{
            "name": "index.md",
            "relative_path": "index.md",
            "size": 10,
            "modified": 1793000000,
            "preview": "Index"
          }]
        }
        """#
        let response = try JSONDecoder.zopedia.decode(
            WikiFilesResponse.self, from: Data(json.utf8)
        )
        XCTAssertEqual(response.totalCount, 2)
        XCTAssertEqual(response.directories["concepts"]?.files.first?.relativePath, "concepts/inflation.md")
        XCTAssertEqual(response.rootFiles.first?.name, "index.md")
    }

    func testWikiQueryDecoding() throws {
        let json = #"""
        {
          "status": "ok",
          "answer": "It rose.",
          "answer_page": "analysis/2026-05-01-10-00-oil.md",
          "context_pages": ["concepts/oil.md", "entities/iran.md"]
        }
        """#
        let response = try JSONDecoder.zopedia.decode(
            WikiQueryResponse.self, from: Data(json.utf8)
        )
        XCTAssertEqual(response.answer, "It rose.")
        XCTAssertEqual(response.contextPages.count, 2)
        XCTAssertEqual(response.answerPage, "analysis/2026-05-01-10-00-oil.md")
    }
}
