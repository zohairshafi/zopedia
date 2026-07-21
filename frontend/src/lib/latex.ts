// Adapted from LibreChat's latex.ts
// https://github.com/danny-avila/LibreChat/blob/main/client/src/utils/latex.ts
//
// Escapes currency dollar signs so they are not misinterpreted as LaTeX math
// delimiters when singleDollarTextMath is enabled.

/**
 * Matches a single $ followed by a number pattern (currency), e.g.:
 *   $5, $1,000, $5.99, $100K, $3.5M
 *
 * Does NOT match:
 *   $$ (display math), \$ (already escaped), $\alpha (LaTeX command)
 */
const CURRENCY_REGEX =
  /(?<![\\$])\$(?!\$)(?=\d+(?:,\d{3})*(?:\.\d+)?[KMBkmb]?(?:\s|$|[^a-zA-Z\d]))/g;

// remark-math v6 only supports $...$ and $$...$$ delimiters. \[...\] and \(...\)
// are valid LaTeX but unsupported here, so they'd otherwise be mangled by
// Markdown escape processing (\[ -> [, \\ -> \). We normalize them to $/$$
// before the Markdown parser runs, which also protects the inner content.
const DISPLAY_BRACKET_RE = /\\\[([\s\S]*?)\\\]/g;
const INLINE_BRACKET_RE = /\\\(([\s\S]*?)\\\)/g;

// Some models (e.g. DeepSeek) emit display math as a bare "[ \begin{env} ...
// \end{env} ]" block instead of \[...\] or $$...$$. A LaTeX environment
// (\begin{...}...\end{...}) is unambiguously math, so wrap those blocks in
// $$...$$. Line-delimited ($$\n ... \n$$) so remark-math's flow parser accepts
// the multi-line content; the surrounding bare [ ] are consumed.
const DISPLAY_ENV_BRACKET_RE = /(^|\n)([ \t]*)\[\s*(\\begin\{[a-zA-Z*]+\}[\s\S]*?\\end\{[a-zA-Z*]+\})\s*\]/g;

// Catch-all for the same models' bare "[ ... ]" display math that does NOT use
// a \begin{} env — e.g. "[ d(\mathbf{p}) = \sqrt{\sum ...} ]". We allow an
// arbitrary non-bracket prefix before the "[" (real LLM output usually labels
// it: "**p**: [...]", "Set p = [...]", "- [...]"), balanced to a "]" at the
// end of the line, and only wrap when the content looks like math (a LaTeX
// command \w or a superscript ^). The closing-]-at-EOL anchor + the math-body
// gate are what exclude prose brackets and markdown links [a](b); the prefix
// is kept on its own line so remark-math still sees $$...$$ as a flow block.
const BARE_DISPLAY_LINE_RE = /^([^\n[\]]*?)\[([\s\S]*?)\][ \t]*$/gm;

/**
 * Find regions inside code blocks (``` ... ``` and ` ... `) so we can skip them.
 * Returns sorted array of [start, end] index pairs.
 */
function findCodeBlockRegions(content: string): Array<[number, number]> {
  const regions: Array<[number, number]> = [];

  // Fenced code blocks: ```...```
  const fencedRe = /```[\s\S]*?```/g;
  let match: RegExpExecArray | null;
  while ((match = fencedRe.exec(content)) !== null) {
    regions.push([match.index, match.index + match[0].length]);
  }

  // Inline code: `...` (but not inside fenced blocks -- we filter below)
  const inlineRe = /`[^`\n]+`/g;
  while ((match = inlineRe.exec(content)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    // Skip if this backtick span falls inside a fenced block
    let inside = false;
    for (const [rs, re] of regions) {
      if (start >= rs && end <= re) {
        inside = true;
        break;
      }
    }
    if (!inside) {
      regions.push([start, end]);
    }
  }

  // Sort by start position for binary search
  regions.sort((a, b) => a[0] - b[0]);
  return regions;
}

/**
 * Binary search to check if a position falls inside any code region.
 */
function isInCodeBlock(
  position: number,
  regions: Array<[number, number]>,
): boolean {
  let lo = 0;
  let hi = regions.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const [start, end] = regions[mid];
    if (position < start) {
      hi = mid - 1;
    } else if (position >= end) {
      lo = mid + 1;
    } else {
      return true;
    }
  }
  return false;
}

/**
 * Preprocess a markdown string to escape currency dollar signs so they are not
 * parsed as LaTeX math delimiters.
 *
 * - `$5` alone becomes `\$5` (currency, not math)
 * - `$\alpha$` is untouched (real LaTeX)
 * - `$$E = mc^2$$` is untouched (display math)
 * - Currency inside code blocks/spans is untouched
 */
export function preprocessLaTeX(content: string): string {
  let out = content;

  // 1. Escape currency $ signs (e.g. $5 -> \$5) so they're not parsed as math.
  if (out.includes("$")) {
    const codeRegions = findCodeBlockRegions(out);
    out = out.replace(CURRENCY_REGEX, (match, offset) =>
      isInCodeBlock(offset, codeRegions) ? match : "\\" + match,
    );
  }

  // 2. Normalize LaTeX bracket delimiters to $ / $$. Skip code blocks.
  // Recompute code regions per pass since earlier passes change offsets.
  if (out.includes("\\[")) {
    const codeRegions = findCodeBlockRegions(out);
    out = out.replace(DISPLAY_BRACKET_RE, (match, offset) =>
      isInCodeBlock(offset, codeRegions) ? match : `$$${match.slice(2, -2)}$$`,
    );
  }
  if (out.includes("\\(")) {
    const codeRegions = findCodeBlockRegions(out);
    out = out.replace(INLINE_BRACKET_RE, (match, offset) =>
      isInCodeBlock(offset, codeRegions) ? match : `$${match.slice(2, -2)}$`,
    );
  }

  // 3. Wrap bare "[ \begin{env} ... \end{env} ]" display-math blocks (some
  //    models emit these instead of \[...\]). \begin{} is unambiguous math.
  if (out.includes("\\begin{")) {
    const codeRegions = findCodeBlockRegions(out);
    out = out.replace(DISPLAY_ENV_BRACKET_RE, (match, lead, indent, body, offset) => {
      const bracketOffset = offset + lead.length + indent.length;
      return isInCodeBlock(bracketOffset, codeRegions)
        ? match
        : `${lead}${indent}$$\n${body}\n$$\n`;
    });
  }

  // 4. Wrap bare "[ ... ]" display math on its own line(s) WITHOUT a \begin{}
  //    env (e.g. "[ d(\mathbf{p}) = \sqrt{\sum ...} ]"). Only fires when the
  //    content looks like math (\command or ^), so prose brackets are left
  //    alone. Runs after the \begin{} pass so env blocks are already handled.
  if (out.includes("[")) {
    const codeRegions = findCodeBlockRegions(out);
    out = out.replace(BARE_DISPLAY_LINE_RE, (match, prefix, body, offset) => {
      if (isInCodeBlock(offset, codeRegions)) return match;
      if (!/\\\w|\^/.test(body)) return match; // not math-looking
      // Keep any prefix (e.g. "**p**:", "Set p =", "- ") on its own line so the
      // $$...$$ stays a remark-math flow block at column 0.
      const prefixTrimmed = prefix.replace(/\s+$/, "");
      return prefixTrimmed
        ? `${prefixTrimmed}\n$$\n${body.trim()}\n$$`
        : `$$\n${body.trim()}\n$$`;
    });
  }

  return out;
}
