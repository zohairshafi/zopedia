// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import type { MessageRecord } from "../types";

interface ContentPart {
  type: string;
  text?: string;
  toolName?: string;
  toolCallId?: string;
  args?: Record<string, unknown>;
  argsText?: string;
  result?: string | { text: string; images?: string[]; sessionId?: string };
  status?: { type: string; reason?: string; error?: unknown };
}

/** Escape HTML entities in plain text. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Block-level markdown parsing ────────────────────────────────

/** Token types produced by the block-level lexer. */
type BlockToken =
  | { type: "fence"; lang: string; code: string }
  | { type: "table"; rows: string[][]; align: string[] }
  | { type: "heading"; level: number; text: string }
  | { type: "hr" }
  | { type: "blockquote"; lines: string[] }
  | { type: "list"; items: { checked: boolean | null; text: string }[]; ordered: boolean }
  | { type: "paragraph"; text: string }
  | { type: "blank" };

/**
 * Lex markdown into block-level tokens.
 * Handles: fenced code blocks, tables, headings, horizontal rules,
 * blockquotes, ordered/unordered/task lists, and paragraphs.
 */
function lexBlocks(markdown: string): BlockToken[] {
  const lines = markdown.split("\n");
  const tokens: BlockToken[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i] ?? "";

    // Fenced code block
    const fenceMatch = line.match(/^(`{3,})(\w*)\s*$/);
    if (fenceMatch) {
      const fence = fenceMatch[1] ?? "";
      const lang = fenceMatch[2] ?? "";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length) {
        if (lines[i]?.startsWith(fence)) {
          i++;
          break;
        }
        codeLines.push(lines[i] ?? "");
        i++;
      }
      tokens.push({ type: "fence", lang, code: codeLines.join("\n") });
      continue;
    }

    // Table (must have at least 2 lines: header + separator)
    if (line.includes("|")) {
      const table = tryParseTable(lines, i);
      if (table) {
        tokens.push({ type: "table", rows: table.rows, align: table.align });
        i = table.nextIndex;
        continue;
      }
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      tokens.push({ type: "hr" });
      i++;
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      tokens.push({
        type: "heading",
        level: (headingMatch[1] ?? "").length,
        text: headingMatch[2] ?? "",
      });
      i++;
      continue;
    }

    // Blockquote (may be multi-line)
    if (line.startsWith("> ")) {
      const bqLines: string[] = [];
      while (i < lines.length && (lines[i] ?? "").startsWith("> ")) {
        bqLines.push((lines[i] ?? "").replace(/^> /, ""));
        i++;
      }
      tokens.push({ type: "blockquote", lines: bqLines });
      continue;
    }

    // Unordered / task list
    const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if (ulMatch) {
      const listItems: { checked: boolean | null; text: string }[] = [];
      let isTaskList = false;
      while (i < lines.length) {
        const liLine = lines[i] ?? "";
        // Allow blank lines between loose list items — peek ahead to
        // see if a list item follows the blank(s), and if so, continue.
        if (liLine.trim() === "") {
          let peek = i + 1;
          while (peek < lines.length && (lines[peek] ?? "").trim() === "") peek++;
          if (peek < lines.length && /^(\s*)[-*+]\s+/.test(lines[peek] ?? "")) {
            i = peek;
            continue;
          }
          break;
        }
        const liMatch = liLine.match(/^(\s*)[-*+]\s+(.*)$/);
        if (!liMatch) break;
        let content = liMatch[2] ?? "";
        // Task list checkbox
        const taskMatch = content.match(/^\[( |x|X)\]\s*(.*)/);
        let checked: boolean | null = null;
        if (taskMatch) {
          isTaskList = true;
          checked = (taskMatch[1] ?? " ").toLowerCase() === "x";
          content = taskMatch[2] ?? "";
        }
        listItems.push({ checked, text: content });
        i++;
      }
      tokens.push({
        type: "list",
        items: listItems,
        ordered: false,
        ...(isTaskList ? {} : {}),
      } as BlockToken);
      continue;
    }

    // Ordered list
    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (olMatch) {
      const listItems: { checked: boolean | null; text: string }[] = [];
      while (i < lines.length) {
        const liLine = lines[i] ?? "";
        // Allow blank lines between loose list items
        if (liLine.trim() === "") {
          let peek = i + 1;
          while (peek < lines.length && (lines[peek] ?? "").trim() === "") peek++;
          if (peek < lines.length && /^\d+\.\s+/.test(lines[peek] ?? "")) {
            i = peek;
            continue;
          }
          break;
        }
        const liMatch = liLine.match(/^\d+\.\s+(.*)$/);
        if (!liMatch) break;
        listItems.push({ checked: null, text: liMatch[1] ?? "" });
        i++;
      }
      tokens.push({ type: "list", items: listItems, ordered: true });
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      tokens.push({ type: "blank" });
      i++;
      continue;
    }

    // Paragraph — collect until blank line or next block token
    const paraLines: string[] = [];
    while (i < lines.length && (lines[i] ?? "").trim() !== "") {
      // Stop if the line would start a new block
      const peek = lines[i] ?? "";
      if (
        peek.startsWith("```") ||
        peek.startsWith("> ") ||
        /^(\s*)[-*+]\s+/.test(peek) ||
        /^\d+\.\s+/.test(peek) ||
        /^(#{1,6})\s+/.test(peek) ||
        /^(-{3,}|\*{3,}|_{3,})\s*$/.test(peek) ||
        (peek.includes("|") && tryParseTable(lines, i) !== null)
      ) {
        break;
      }
      paraLines.push(peek);
      i++;
    }
    if (paraLines.length > 0) {
      tokens.push({ type: "paragraph", text: paraLines.join("\n") });
    }
  }

  return tokens;
}

/** Try to parse a GFM table starting at the given line index. Returns null if not a valid table. */
function tryParseTable(
  lines: string[],
  start: number,
): { rows: string[][]; align: string[]; nextIndex: number } | null {
  const headerLine = lines[start];
  const sepLine = lines[start + 1];
  if (!headerLine || !sepLine) return null;
  if (!/^\|.*\|$/.test(headerLine.trim()) && !/^[^|]+\|/.test(headerLine.trim())) return null;
  if (!/^[\s:| -]+$/.test(sepLine.trim())) return null;

  const align = parseTableAlign(sepLine);
  const rows: string[][] = [];
  rows.push(parseTableRow(headerLine));

  let i = start + 2;
  while (i < lines.length) {
    const rowLine = lines[i] ?? "";
    if (!rowLine.includes("|")) break;
    rows.push(parseTableRow(rowLine));
    i++;
  }

  return { rows, align, nextIndex: i };
}

function parseTableAlign(sep: string): string[] {
  return sep
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => {
      const trimmed = cell.trim();
      if (trimmed.startsWith(":") && trimmed.endsWith(":")) return "center";
      if (trimmed.endsWith(":")) return "right";
      return "left";
    });
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

// ── Inline markdown rendering ───────────────────────────────────

/**
 * Render inline markdown (bold, italic, code, links, images, strikethrough).
 * Must be called on text that has already had block-level tokens extracted.
 */
function renderInline(text: string): string {
  let out = text;

  // Images (must come before links)
  out = out.replace(
    /!\[([^\]]*)\]\(([^)]+)\)/g,
    '<img src="$2" alt="$1" loading="lazy">',
  );

  // Links
  out = out.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>',
  );

  // Inline code
  out = out.replace(/`([^`]+)`/g, (_m: string, code: string) => `<code>${escapeHtml(code)}</code>`);

  // Bold
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // Italic
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // Strikethrough
  out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");

  return out;
}

/** Render a fenced code block to HTML. */
function renderFence(lang: string, code: string): string {
  const langLabel = lang ? `<span class="code-lang">${escapeHtml(lang)}</span>` : "";
  return `<pre>${langLabel}<code class="language-${escapeHtml(lang)}">${escapeHtml(code.trimEnd())}</code></pre>`;
}

// ── Tool result parsing (web_search) ────────────────────────────

interface ParsedSource {
  title: string;
  url: string;
  snippet: string;
}

const RE_BLOCK_SEP = /\n---\n/;
const RE_TITLE = /Title:\s*(.+)/;
const RE_URL = /URL:\s*(.+)/;
const RE_SNIPPET = /Snippet:\s*(.+)/s;

function parseSearchResults(raw: string): ParsedSource[] {
  if (!raw) return [];
  const blocks = raw.split(RE_BLOCK_SEP).filter(Boolean);
  const sources: ParsedSource[] = [];
  for (const block of blocks) {
    const titleMatch = block.match(RE_TITLE);
    const urlMatch = block.match(RE_URL);
    const snippetMatch = block.match(RE_SNIPPET);
    if (titleMatch && urlMatch) {
      sources.push({
        title: titleMatch[1]!.trim(),
        url: urlMatch[1]!.trim(),
        snippet: snippetMatch?.[1]?.trim() ?? "",
      });
    }
  }
  return sources;
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// ── Full markdown rendering (block + inline) ────────────────────

function renderMarkdown(markdown: string): string {
  const tokens = lexBlocks(markdown);
  const htmlParts: string[] = [];

  for (let t = 0; t < tokens.length; t++) {
    const token = tokens[t]!;

    switch (token.type) {
      case "fence":
        htmlParts.push(renderFence(token.lang, token.code));
        break;

      case "table": {
        const { rows, align } = token;
        const thead = `<thead><tr>${rows[0]!
          .map(
            (cell, ci) =>
              `<th style="text-align:${align[ci] ?? "left"}">${renderInline(cell)}</th>`,
          )
          .join("")}</tr></thead>`;
        const tbody = `<tbody>${rows
          .slice(1)
          .map(
            (row) =>
              `<tr>${row
                .map(
                  (cell, ci) =>
                    `<td style="text-align:${align[ci] ?? "left"}">${renderInline(cell)}</td>`,
                )
                .join("")}</tr>`,
          )
          .join("")}</tbody>`;
        htmlParts.push(`<div class="table-wrapper"><table>${thead}${tbody}</table></div>`);
        break;
      }

      case "heading":
        htmlParts.push(
          `<h${token.level}>${renderInline(token.text)}</h${token.level}>`,
        );
        break;

      case "hr":
        htmlParts.push("<hr>");
        break;

      case "blockquote":
        htmlParts.push(
          `<blockquote>${token.lines.map((l) => renderInline(l)).join("<br>")}</blockquote>`,
        );
        break;

      case "list": {
        const tag = token.ordered ? "ol" : "ul";
        const items = token.items
          .map((item) => {
            const isTask = item.checked !== null;
            const checkbox = isTask
              ? `<input type="checkbox" disabled${item.checked ? " checked" : ""}>`
              : "";
            const cls = isTask ? ' class="task-list-item"' : "";
            return `<li${cls}>${checkbox}${renderInline(item.text)}</li>`;
          })
          .join("");
        htmlParts.push(`<${tag}>${items}</${tag}>`);
        break;
      }

      case "paragraph":
        htmlParts.push(`<p>${renderInline(token.text)}</p>`);
        break;

      case "blank":
        // skip — spacing is handled by CSS margins
        break;
    }
  }

  return htmlParts.join("\n");
}

// ── Tool icons (inline SVGs matching lucide-react icons) ─────────

function globeIcon(): string {
  return `<svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20"/><path d="M2 12h20"/></svg>`;
}

function codeIcon(): string {
  return `<svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`;
}

function terminalIcon(): string {
  return `<svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`;
}

function vectorSquareIcon(): string {
  return `<svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="7" y="7" width="10" height="10" rx="1"/></svg>`;
}

// ── Content part rendering ──────────────────────────────────────

/** Get the result text from a tool result (handles both string and object forms). */
function getResultText(result: ContentPart["result"]): string {
  if (result === undefined) return "";
  if (typeof result === "string") return result;
  return result.text ?? JSON.stringify(result);
}

/**
 * Render a web_search tool call — matches WebSearchToolUI in the app.
 * Shows source pills with favicons when sources are parsed from the result.
 */
function renderWebSearchTool(part: ContentPart): string {
  const query = (part.args as { query?: string })?.query ?? "";
  const url = ((part.args as { url?: string })?.url ?? "").trim();
  const isUrlFetch = !!url;
  const displayDomain = (() => {
    if (!url) return "";
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return parsed.hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  })();

  const label = isUrlFetch
    ? displayDomain
      ? `Read ${displayDomain}`
      : "Read page"
    : query
      ? `Searched "${query}"`
      : "Web Search";

  const resultText = getResultText(part.result);
  const sources = resultText ? parseSearchResults(resultText) : [];

  let bodyHtml = "";
  if (sources.length > 0) {
    bodyHtml =
      '<div class="tool-sources">' +
      sources
        .map((src) => {
          const domain = extractDomain(src.url);
          const faviconUrl = `https://www.google.com/s2/favicons?domain=${domain}&sz=32`;
          return (
            `<a href="${escapeHtml(src.url)}" target="_blank" rel="noopener" class="source-pill">` +
            `<img src="${faviconUrl}" alt="" class="source-favicon" onerror="this.style.display='none'">` +
            `<span class="source-title">${escapeHtml(src.title)}</span>` +
            `</a>`
          );
        })
        .join("") +
      "</div>";
  } else if (resultText) {
    bodyHtml = renderToolArgsAndResult(part);
  }

  return renderToolCallWrapper(label, bodyHtml, part.status, globeIcon());
}

/** Render a python tool call — shows code block and output section. */
function renderPythonTool(part: ContentPart): string {
  const code = (part.args as { code?: string })?.code ?? "";
  const firstLine = code.split("\n")[0]?.trim() ?? "";
  const label = firstLine ? `Python: ${firstLine}` : "Python";

  let bodyHtml = "";
  // Code block
  if (code) {
    bodyHtml += `<pre class="tool-code"><code class="language-python">${escapeHtml(code)}</code></pre>`;
  }

  // Output
  const result = part.result;
  if (result !== undefined) {
    let outputText: string;
    let images: string[] = [];
    if (typeof result === "object" && result !== null) {
      outputText = result.text ?? "";
      images = result.images ?? [];
    } else {
      outputText = String(result);
    }
    if (outputText) {
      bodyHtml +=
        `<div class="tool-output-section">` +
        `<div class="tool-output-header">output</div>` +
        `<pre class="tool-output"><code>${escapeHtml(outputText)}</code></pre>` +
        `</div>`;
    }
    if (images.length > 0) {
      const sessionId =
        typeof result === "object" && result !== null ? result.sessionId ?? "_default" : "_default";
      bodyHtml +=
        `<div class="tool-images">` +
        images
          .map(
            (img) =>
              `<img src="/api/inference/sandbox/${escapeHtml(sessionId)}/output/${escapeHtml(img)}" alt="Python output image" loading="lazy">`,
          )
          .join("") +
        `</div>`;
    }
  }

  return renderToolCallWrapper(label, bodyHtml, part.status, codeIcon());
}

/** Render a terminal tool call — shows command and output. */
function renderTerminalTool(part: ContentPart): string {
  const command = (part.args as { command?: string })?.command ?? "";
  const label = command ? `$ ${command}` : "Terminal";

  let bodyHtml = "";
  if (command) {
    bodyHtml += `<pre class="tool-code"><code>${escapeHtml(command)}</code></pre>`;
  }

  const resultText = getResultText(part.result);
  if (resultText) {
    bodyHtml +=
      `<div class="tool-output-section">` +
      `<div class="tool-output-header">output</div>` +
      `<pre class="tool-output"><code>${escapeHtml(resultText)}</code></pre>` +
      `</div>`;
  }

  return renderToolCallWrapper(label, bodyHtml, part.status, terminalIcon());
}

/** Render args + result for generic/unknown tool calls. */
function renderToolArgsAndResult(part: ContentPart): string {
  const argsText = part.argsText ?? (part.args ? JSON.stringify(part.args, null, 2) : "");
  const resultText = getResultText(part.result);

  let html = "";
  if (argsText) {
    html += `<div class="tool-section"><div class="tool-section-header">Arguments</div><pre class="tool-pre"><code>${escapeHtml(argsText)}</code></pre></div>`;
  }
  if (resultText) {
    const truncated =
      resultText.length > 5000
        ? resultText.slice(0, 5000) + "\n... (truncated)"
        : resultText;
    html += `<div class="tool-section"><div class="tool-section-header">Result</div><pre class="tool-pre"><code>${escapeHtml(truncated)}</code></pre></div>`;
  }
  return html;
}

/** Wrap tool content in a details/summary matching the UI collapsible pattern. */
function renderToolCallWrapper(
  label: string,
  bodyHtml: string,
  status?: ContentPart["status"],
  customIcon?: string,
): string {
  const statusType = status?.type ?? "complete";
  const isCancelled = statusType === "incomplete" && status?.reason === "cancelled";
  const prefix = isCancelled ? "Cancelled tool" : "Used tool";
  const cancelledClass = isCancelled ? " cancelled" : "";

  // Use the tool-specific icon, or fall back to the generic status icon
  const iconSvg = customIcon ?? vectorSquareIcon();

  return `
<details class="tool-call${cancelledClass}">
  <summary class="tool-summary">
    <span class="tool-summary-left">
      ${iconSvg}
      <span class="tool-label">${escapeHtml(prefix)}: <strong>${escapeHtml(label)}</strong></span>
    </span>
    <svg class="tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </summary>
  <div class="tool-body">${bodyHtml}</div>
</details>`;
}

/** Render a single content part to an HTML string. */
function renderContentPart(part: ContentPart): string {
  switch (part.type) {
    case "text": {
      const text = part.text ?? "";
      return renderMarkdown(text);
    }
    case "reasoning": {
      const reasoning = part.text ?? "";
      return `<details class="reasoning"><summary>Thinking</summary><div class="reasoning-content">${renderMarkdown(reasoning)}</div></details>`;
    }
    case "tool-call": {
      const toolName = part.toolName ?? "unknown";
      switch (toolName) {
        case "web_search":
          return renderWebSearchTool(part);
        case "python":
          return renderPythonTool(part);
        case "terminal":
          return renderTerminalTool(part);
        default:
          return renderToolCallWrapper(
            toolName,
            renderToolArgsAndResult(part),
            part.status,
          );
      }
    }
    default:
      return "";
  }
}

/** Format a timestamp for display. */
function formatTime(ms: number): string {
  return new Date(ms).toLocaleString();
}

/**
 * Fetch a zopedia logo as a base64 data URI.
 * `variant` selects light ("logo_main_light.png") or dark ("logo_main.png").
 * Falls back to an empty string if the fetch fails.
 */
async function getLogoBase64(variant: "light" | "dark"): Promise<string> {
  try {
    const filename = variant === "light" ? "/circle-logo-small-light.png" : "/circle-logo-small.png";
    const resp = await fetch(filename);
    if (!resp.ok) return "";
    const blob = await resp.blob();
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result as string);
      reader.readAsDataURL(blob);
    });
  } catch {
    return "";
  }
}

/**
 * Export all messages from a thread as a self-contained HTML file.
 * Design language matches the zopedia app: shadcn Maia teal-green palette,
 * Inter/Helix/Fira Code fonts, user message bubbles with asymmetric radius,
 * assistant messages without bubbles, and dual logo variants for light/dark.
 */
export async function exportThreadAsHtml(
  messages: MessageRecord[],
  threadTitle?: string,
): Promise<void> {
  const [logoLight, logoDark] = await Promise.all([
    getLogoBase64("light"),
    getLogoBase64("dark"),
  ]);
  const title = threadTitle || "zopedia Chat";
  const now = new Date().toLocaleString();

  let messagesHtml = "";
  for (const msg of messages) {
    const role = msg.role;
    const time = formatTime(msg.createdAt);
    const roleLabel = role === "user" ? "You" : role === "assistant" ? "zopedia" : "System";

    const parts = (msg.content ?? []) as ContentPart[];
    const contentHtml = parts.map(renderContentPart).join("");

    const roleClass = role === "user" ? "user" : "assistant";

    messagesHtml += `
    <div class="message ${roleClass}">
      <div class="message-header">
        <span class="role">${escapeHtml(roleLabel)}</span>
        <span class="time">${escapeHtml(time)}</span>
      </div>
      <div class="message-body">${contentHtml || '<em class="empty">(empty message)</em>'}</div>
    </div>`;
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(title)}</title>
<style>
  /* ── Fonts ─────────────────────────────────────────── */
  @font-face {
    font-family: "Inter Variable";
    src: url("/fonts/InterVariable.woff2") format("woff2");
    font-weight: 100 900;
    font-style: normal;
    font-display: swap;
  }
  @font-face {
    font-family: "Hellix";
    src: url("/fonts/Hellix-Regular.woff") format("woff");
    font-weight: 400;
    font-style: normal;
    font-display: swap;
  }
  @font-face {
    font-family: "Hellix";
    src: url("/fonts/Hellix-Medium.woff") format("woff");
    font-weight: 500;
    font-style: normal;
    font-display: swap;
  }
  @font-face {
    font-family: "Hellix";
    src: url("/fonts/Hellix-SemiBold.woff2") format("woff2"),
         url("/fonts/Hellix-SemiBold.woff") format("woff");
    font-weight: 600;
    font-style: normal;
    font-display: swap;
  }
  @font-face {
    font-family: "Fira Code";
    src: url("/fonts/FiraCode-VariableFont_wght.ttf") format("truetype-variations");
    font-weight: 300 700;
    font-style: normal;
    font-display: swap;
  }

  /* ── Base / Variables ──────────────────────────────── */
  :root {
    --bg: #ffffff;
    --fg: #444444;
    --fg-muted: #8b8b8b;
    --primary: #44b89a;
    --primary-hover: #3aa089;
    --secondary: #eef5f2;
    --secondary-fg: #295246;
    --border: #e5edeb;
    --card: #ffffff;
    --code-bg: #181818;
    --code-fg: #cdd6f4;
    --user-bubble-bg: #f5f5f5;
    --reasoning-bg: #f5f5f5;
    --reasoning-border: #e5e5e5;
    --radius: 16px;
    --font-sans: "Inter Variable", ui-sans-serif, sans-serif, system-ui;
    --font-heading: "Hellix", "Space Grotesk Variable", var(--font-sans);
    --font-mono: "Fira Code", ui-monospace, monospace;
  }

  /* ── Dark mode overrides ───────────────────────────── */
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1a1b1e;
      --fg: #d4d4d4;
      --fg-muted: #999999;
      --primary: #44b89a;
      --primary-hover: #5cc9ad;
      --secondary: #2e3035;
      --secondary-fg: #d4d4d4;
      --border: #2e3035;
      --card: #222427;
      --code-bg: #181818;
      --code-fg: #cdd6f4;
      --user-bubble-bg: #222427;
      --reasoning-bg: #2a2a2a;
      --reasoning-border: #3a3a3a;
    }
    .logo-light { display: none; }
    .logo-dark { display: block; }
  }
  @media (prefers-color-scheme: light) {
    .logo-light { display: block; }
    .logo-dark { display: none; }
  }

  /* ── Reset ─────────────────────────────────────────── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--font-sans);
    background: var(--bg);
    color: var(--fg);
    line-height: 1.6;
    max-width: 900px;
    margin: 0 auto;
    padding: 20px;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* ── Header ────────────────────────────────────────── */
  header {
    padding: 32px 0 24px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
  }
  .header-brand {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 16px;
    user-select: none;
  }
  .header-brand img {
    height: 34px;
    width: 34px;
    border-radius: 9999px;
    object-fit: cover;
  }
  .brand {
    font-family: var(--font-heading);
    font-size: 21px;
    font-weight: 600;
    line-height: 1;
    letter-spacing: -0.01em;
    color: #000000;
  }
  @media (prefers-color-scheme: dark) {
    .brand {
      color: #ffffff;
      letter-spacing: 0.02em;
    }
  }
  header h1 {
    font-family: var(--font-heading);
    font-size: 1.15rem;
    font-weight: 600;
    color: var(--fg);
    letter-spacing: -0.01em;
  }
  header .export-info {
    font-size: 0.8rem;
    color: var(--fg-muted);
    margin-top: 4px;
  }

  /* ── Messages ──────────────────────────────────────── */
  .message {
    margin-bottom: 20px;
    font-size: 15.5px;
    font-weight: 450;
  }

  /* User: right-aligned, light bubble, asymmetric radius */
  .message.user {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    max-width: 80%;
    margin-left: auto;
  }
  .message.user .message-body {
    background: var(--user-bubble-bg);
    border-radius: var(--radius);
    border-top-right-radius: 4px;
    padding: 10px 16px;
    color: var(--fg);
    width: fit-content;
  }

  /* Assistant: no bubble, flush against background, full width */
  .message.assistant {
    max-width: 100%;
    margin-right: auto;
  }
  .message.assistant .message-body {
    color: var(--fg);
    line-height: 1.625;
  }

  /* Header row */
  .message-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
    font-size: 0.8rem;
    width: 100%;
  }
  .message-header .role {
    font-weight: 600;
    color: var(--fg-muted);
  }
  .message-header .time {
    color: var(--fg-muted);
    opacity: 0.7;
  }

  /* ── Prose within messages ─────────────────────────── */
  .message-body p { margin-bottom: 8px; }
  .message-body p:last-child { margin-bottom: 0; }

  .message-body h1, .message-body h2, .message-body h3,
  .message-body h4, .message-body h5, .message-body h6 {
    font-family: var(--font-heading);
    margin: 12px 0 6px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .message-body h1 { font-size: 1.3rem; }
  .message-body h2 { font-size: 1.15rem; }
  .message-body h3 { font-size: 1.05rem; }
  .message-body h4 { font-size: 1rem; }
  .message-body h5 { font-size: 0.95rem; }
  .message-body h6 { font-size: 0.9rem; }

  .message-body ul, .message-body ol {
    margin: 8px 0;
    padding-left: 24px;
  }
  .message-body li { margin-bottom: 2px; }
  .message-body li.task-list-item {
    list-style: none;
    margin-left: -20px;
  }
  .message-body li.task-list-item input[type="checkbox"] {
    margin-right: 6px;
    accent-color: var(--primary);
    pointer-events: none;
  }

  .message-body code {
    background: var(--secondary);
    color: var(--secondary-fg);
    padding: 2px 5px;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 0.88em;
  }
  .message-body pre {
    background: var(--code-bg);
    color: var(--code-fg);
    padding: 14px 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 10px 0;
    font-size: 0.85rem;
    font-family: var(--font-mono);
    line-height: 1.55;
    position: relative;
  }
  .message-body pre .code-lang {
    position: absolute;
    top: 0;
    right: 0;
    padding: 2px 8px;
    font-size: 0.7rem;
    font-family: var(--font-sans);
    color: var(--code-fg);
    opacity: 0.5;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .message-body pre code {
    background: none;
    padding: 0;
    color: inherit;
    font-size: inherit;
  }
  .message-body a {
    color: var(--primary);
    text-decoration: underline;
    text-decoration-color: color-mix(in srgb, var(--primary) 40%, transparent);
    text-underline-offset: 2px;
  }
  .message-body a:hover {
    text-decoration-color: var(--primary);
  }
  .message-body blockquote {
    border-left: 3px solid var(--border);
    padding-left: 12px;
    color: var(--fg-muted);
    margin: 8px 0;
  }
  .message-body hr {
    border: 0;
    border-top: 1px solid var(--border);
    margin: 16px 0;
  }
  .message-body img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    margin: 8px 0;
  }
  .message-body strong { font-weight: 600; }
  .message-body em { font-style: italic; }
  .message-body del { text-decoration: line-through; opacity: 0.7; }

  /* ── Tables ────────────────────────────────────────── */
  .table-wrapper {
    overflow-x: auto;
    margin: 10px 0;
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  .message-body table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9em;
  }
  .message-body thead {
    border-bottom: 2px solid var(--border);
  }
  .message-body th {
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
    color: var(--fg-muted);
    font-size: 0.85em;
  }
  .message-body td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }
  .message-body tr:last-child td {
    border-bottom: none;
  }

  /* ── Reasoning (collapsible, matches app's Reasoning component) ── */
  details.reasoning {
    margin: 0 0 16px 0;
    width: 100%;
    border: 1px solid var(--reasoning-border);
    border-radius: 8px;
    padding: 8px 12px;
  }
  details.reasoning summary {
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--fg-muted);
    font-size: 0.875rem;
    line-height: 1.25rem;
    list-style: none;
    transition: color 0.15s;
  }
  details.reasoning summary:hover {
    color: var(--fg);
  }
  details.reasoning summary::-webkit-details-marker { display: none; }
  details.reasoning summary::marker { display: none; content: ""; }
  .reasoning-content {
    margin-top: 8px;
    padding-top: 8px;
    color: var(--fg);
    opacity: 0.85;
    font-size: 0.84375rem;
    line-height: 1.625;
    max-height: 256px;
    overflow-y: auto;
  }

  /* ── Tool calls (matches ToolFallback UI — minimal, no colored box) ── */
  details.tool-call {
    margin: 0;
    padding: 4px 0;
    width: 100%;
  }
  details.tool-call.cancelled {
    opacity: 0.6;
  }

  .tool-summary {
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 0;
    font-size: 0.875rem;
    line-height: 1.25rem;
    list-style: none;
    user-select: none;
    color: var(--fg-muted);
    transition: color 0.15s;
  }
  .tool-summary:hover {
    color: var(--fg);
  }
  .tool-summary::-webkit-details-marker { display: none; }
  .tool-summary::marker { display: none; content: ""; }

  .tool-summary-left {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    line-height: 1;
  }

  .tool-icon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    color: var(--fg-muted);
  }

  .tool-label {
    line-height: 1;
  }
  .tool-label strong {
    font-weight: 500;
    color: var(--fg);
    opacity: 0.85;
  }

  .tool-chevron {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    transition: transform 0.2s ease;
  }
  details.tool-call[open] .tool-chevron {
    transform: rotate(180deg);
  }

  .tool-body {
    margin-top: 4px;
    padding-left: 24px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Tool section (args / result blocks) */
  .tool-section-header {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--fg-muted);
    margin-bottom: 2px;
  }
  .tool-pre {
    font-family: var(--font-mono);
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 400px;
    overflow-y: auto;
    color: var(--fg);
  }
  .tool-pre code {
    background: none;
    padding: 0;
    color: inherit;
    font-size: inherit;
    font-family: inherit;
  }

  /* Python/terminal code block inside tool */
  .tool-code {
    background: var(--code-bg);
    color: var(--code-fg);
    padding: 10px 12px;
    border-radius: 6px;
    font-size: 0.8rem;
    font-family: var(--font-mono);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 300px;
    overflow-y: auto;
  }
  .tool-code code {
    background: none;
    padding: 0;
    color: inherit;
    font-size: inherit;
    font-family: inherit;
  }

  /* Output section */
  .tool-output-section {
    border-top: 1px dashed var(--border);
    padding-top: 8px;
  }
  .tool-output-header {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
  }
  .tool-output {
    font-size: 0.8rem;
    font-family: var(--font-mono);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 300px;
    overflow-y: auto;
    color: var(--fg);
  }
  .tool-output code {
    background: none;
    padding: 0;
    color: inherit;
    font-size: inherit;
    font-family: inherit;
  }

  /* Tool images */
  .tool-images {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 4px;
  }
  .tool-images img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    border: 1px solid var(--border);
  }

  /* Web search source pills */
  .tool-sources {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .source-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border: 1px solid var(--border);
    border-radius: 9999px;
    font-size: 0.8rem;
    color: var(--fg);
    text-decoration: none;
    transition: border-color 0.15s;
    max-width: 280px;
  }
  .source-pill:hover {
    border-color: var(--fg-muted);
  }
  .source-favicon {
    width: 12px;
    height: 12px;
    flex-shrink: 0;
    border-radius: 2px;
  }
  .source-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .empty { color: var(--fg-muted); }
</style>
</head>
<body>
<header>
  <div class="header-brand">
    ${logoLight ? `<img class="logo logo-light" src="${logoLight}" alt="zopedia Logo">` : ""}
    ${logoDark ? `<img class="logo logo-dark" src="${logoDark}" alt="zopedia Logo">` : ""}
    <span class="brand">zopedia</span>
  </div>
  <h1>${escapeHtml(title)}</h1>
  <p class="export-info">Exported on ${escapeHtml(now)} &middot; ${messages.length} message${messages.length !== 1 ? "s" : ""}</p>
</header>
<main>
${messagesHtml}
</main>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safeTitle = (threadTitle || "zopedia-chat")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
  a.download = `zopedia-${safeTitle}-${new Date().toISOString().slice(0, 10)}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
