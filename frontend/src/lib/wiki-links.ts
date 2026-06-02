/**
 * Wiki link detection and conversion for markdown content.
 *
 * Converts [[page/path]] wiki-link syntax and plain .md path references
 * into clickable markdown links that open the wiki page.
 */

const WIKI_LINK_RE = /\[\[([^\]]+)\]\]/g;

// Match wiki-style paths: concepts/topic.md, entities/person.md, etc.
const WIKI_PATH_RE = /(?<![\[\(`\/])([a-z][\w-]*\/[\w\/-]+\.md)(?![\]\)`])/gi;

// Match analysis paths even without .md: analysis/2026-05-01-...-title-slug
const ANALYSIS_PATH_RE = /(?<![\[\(`\/])(analysis\/\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[\w-]+)(?![\]\)`])/gi;

/**
 * Resolve a wiki page reference (title or path) to a wiki file path.
 */
function resolveWikiPath(ref: string): string {
  const trimmed = ref.trim();
  if (trimmed.includes("/") || trimmed.includes(".")) {
    return trimmed.replace(/\.md$/i, "") + ".md";
  }
  return trimmed.replace(/\s+/g, "-").toLowerCase() + ".md";
}

/**
 * Preprocess markdown text to convert wiki references into clickable links.
 * Handles both [[Page Name]] wikilink syntax and plain path/to/page.md references.
 * Links point to /api/inference/wiki-file?path=... which the backend serves as markdown.
 */
export function preprocessWikiLinks(text: string): string {
  // Step 1: Convert [[wiki links]]
  text = text.replace(WIKI_LINK_RE, (_match, ref: string) => {
    const path = resolveWikiPath(ref);
    return `[${ref}](/api/inference/wiki-file?path=${encodeURIComponent(path)})`;
  });

  // Step 2: Convert plain .md path references that look like wiki pages
  text = text.replace(WIKI_PATH_RE, (match) => {
    const path = resolveWikiPath(match);
    return `[${match}](/api/inference/wiki-file?path=${encodeURIComponent(path)})`;
  });

  // Step 3: Convert analysis/YYYY-MM-DD-HH-MM-title-slug paths (without .md)
  text = text.replace(ANALYSIS_PATH_RE, (match) => {
    const path = match + ".md";
    return `[${match}](/api/inference/wiki-file?path=${encodeURIComponent(path)})`;
  });

  return text;
}
