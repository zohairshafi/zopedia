import Foundation
import Markdown

/// Builds a self-contained HTML document for a conversation.
public enum ChatHTMLExporter {
    public static func html(
        title: String,
        messages: [ChatMessage],
        serverURL: String? = nil,
        generatedAt: Date = Date()
    ) -> String {
        let body = messages.map { messageHTML($0, serverURL: serverURL) }.joined(separator: "\n")
        let exported = displayDate(generatedAt)
        return """
        <!doctype html>
        <html lang="en">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>\(escape(title))</title>
        <style>
        :root {
          --bg: #ffffff; --fg: #3f3f3f; --muted: #717171; --border: #dfe7e3;
          --muted-bg: #f7f7f7; --primary: #14b789; --code-bg: #f6f6f6;
          --bubble: #f5f5f5; --card: #ffffff;
        }
        @media (prefers-color-scheme: dark) {
          :root {
            --bg: #1a1b1e; --fg: #d4d4d4; --muted: #999999; --border: #2e3035;
            --muted-bg: #2e3035; --primary: #14b789; --code-bg: #181818;
            --bubble: #222427; --card: #222427;
          }
        }
        * { box-sizing: border-box; }
        body {
          margin: 0; background: var(--bg); color: var(--fg);
          font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        main { max-width: 860px; margin: 0 auto; padding: 40px 22px 64px; }
        header { margin-bottom: 28px; }
        h1 { font-size: 28px; margin: 0 0 6px; }
        .exported { color: var(--muted); font-size: 13px; }
        .message { margin: 22px 0; }
        .message.user { display: flex; justify-content: flex-end; }
        .bubble {
          background: var(--bubble); border-radius: 16px; border-top-right-radius: 4px;
          padding: 10px 14px; max-width: 80%;
        }
        .message.assistant, .message.system { max-width: 100%; }
        .role { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
        .meta { font-size: 11px; color: var(--muted); margin-top: 4px; }
        .message.user .meta { text-align: right; }
        a { color: var(--primary); text-decoration: underline; text-underline-offset: 2px; }
        p { margin: 0 0 12px; }
        h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 22px 0 8px; }
        ul, ol { margin: 0 0 12px; padding-left: 24px; }
        blockquote { margin: 12px 0; padding-left: 12px; border-left: 3px solid var(--border); color: var(--muted); }
        code {
          font: 0.9em ui-monospace, SFMono-Regular, Menlo, monospace;
          background: var(--muted-bg); border-radius: 4px; padding: 1px 4px;
        }
        pre {
          background: var(--code-bg); border: 1px solid var(--border); border-radius: 10px;
          padding: 12px; overflow: auto;
        }
        pre code { background: transparent; padding: 0; }
        table {
          width: 100%; border-collapse: collapse; border: 1px solid var(--border);
          border-radius: 12px; overflow: hidden; margin: 12px 0;
        }
        th, td { text-align: left; padding: 8px 14px; border-bottom: 1px solid var(--border); }
        th { background: var(--muted-bg); font-weight: 600; }
        tr:last-child td { border-bottom: 0; }
        details {
          border: 1px solid var(--border); border-radius: 10px;
          background: var(--muted-bg); padding: 10px 12px; margin: 10px 0;
        }
        details summary { cursor: pointer; color: var(--muted); font-size: 13px; }
        details[open] summary { margin-bottom: 8px; }
        .tool-name { font-weight: 600; }
        .tool pre { background: var(--code-bg); }
        hr { border: 0; border-top: 1px solid var(--border); margin: 24px 0; }
        </style>
        </head>
        <body>
        <main>
        <header>
          <h1>\(escape(title))</h1>
          <div class="exported">Exported from Zopedia on \(escape(exported))</div>
        </header>
        \(body)
        </main>
        </body>
        </html>
        """
    }

    private static func messageHTML(_ message: ChatMessage, serverURL: String?) -> String {
        let role: String
        switch message.role {
        case .user: role = "You"
        case .assistant: role = "Zopedia"
        case .system: role = "System"
        case .tool: role = "Tool"
        }

        var content = ""
        if let reasoning = message.reasoningContent, !reasoning.isEmpty {
            content += """
            <details><summary>Reasoning</summary>
            \(markdownHTML(reasoning, serverURL: serverURL))
            </details>
            """
        }

        switch message.content {
        case .text(let text):
            content += markdownHTML(text, serverURL: serverURL)
        case .parts(let parts):
            for part in parts {
                switch part {
                case .text(let text):
                    content += markdownHTML(text, serverURL: serverURL)
                case .reasoning(let text):
                    content += """
                    <details><summary>Reasoning</summary>
                    \(markdownHTML(text, serverURL: serverURL))
                    </details>
                    """
                case .tool(let tool):
                    content += toolHTML(tool)
                case .unknown:
                    break
                }
            }
        case .object(let value):
            content += "<pre><code>\(escape(value.prettyPrinted))</code></pre>"
        }

        let stamp = message.createdAt.timeIntervalSince1970 > 0
            ? "<div class=\"meta\">\(escape(displayDate(message.createdAt)))</div>"
            : ""

        if message.role == .user {
            return """
            <article class="message user">
              <div>
                <div class="bubble">\(content)</div>
                \(stamp)
              </div>
            </article>
            """
        }

        return """
        <article class="message \(message.role == .assistant ? "assistant" : "system")">
          <div class="role">\(role)</div>
          \(content)
          \(stamp)
        </article>
        """
    }

    private static func toolHTML(_ tool: ToolCallPart) -> String {
        let args = tool.args?.prettyPrinted ?? ""
        let result = tool.result ?? ""
        var body = ""
        if !args.isEmpty {
            body += "<pre><code>\(escape(args))</code></pre>"
        }
        if !result.isEmpty {
            body += "<pre><code>\(escape(result))</code></pre>"
        }
        return """
        <details class="tool">
          <summary><span class="tool-name">\(escape(tool.toolName))</span></summary>
          \(body)
        </details>
        """
    }

    private static func markdownHTML(_ text: String, serverURL: String?) -> String {
        let processed = WikiLinkPreprocessor.preprocess(text)
        var escaper = HTMLEscapingRewriter()
        let document = Document(parsing: processed)
        let safeDocument = escaper.visit(document) ?? document
        var html = HTMLFormatter.format(safeDocument)
        if let serverURL, !serverURL.isEmpty {
            let base = serverURL.hasSuffix("/") ? String(serverURL.dropLast()) : serverURL
            html = html.replacingOccurrences(
                of: "href=\"zopedia://wiki?path=",
                with: "href=\"\(base)/api/inference/wiki-file?path="
            )
        }
        return html
    }

    /// HTMLFormatter emits Text/code verbatim, so escape those nodes first.
    /// Raw HTML is rewritten as literal text instead of being emitted.
    private struct HTMLEscapingRewriter: MarkupRewriter {
        mutating func visitText(_ text: Text) -> Markup? {
            Text(ChatHTMLExporter.escape(text.string))
        }

        mutating func visitInlineCode(_ inlineCode: InlineCode) -> Markup? {
            InlineCode(ChatHTMLExporter.escape(inlineCode.code))
        }

        mutating func visitCodeBlock(_ codeBlock: CodeBlock) -> Markup? {
            CodeBlock(
                language: codeBlock.language,
                ChatHTMLExporter.escape(codeBlock.code)
            )
        }

        mutating func visitHTMLBlock(_ html: HTMLBlock) -> Markup? {
            Paragraph(Text(ChatHTMLExporter.escape(html.rawHTML)))
        }

        mutating func visitInlineHTML(_ inlineHTML: InlineHTML) -> Markup? {
            Text(ChatHTMLExporter.escape(inlineHTML.rawHTML))
        }
    }

    fileprivate static func escape(_ text: String) -> String {
        text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }

    private static func displayDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}
