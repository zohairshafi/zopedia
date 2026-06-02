# fetch URLs (tweet/arxiv/pdf/web) and save as annotated markdown
from __future__ import annotations
import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from graphify.security import safe_fetch, safe_fetch_text, validate_url

logger = logging.getLogger(__name__)


def _safe_filename(url: str, suffix: str) -> str:
    """Turn a URL into a safe filename."""
    parsed = urllib.parse.urlparse(url)
    name = parsed.netloc + parsed.path
    name = re.sub(r"[^\w\-]", "_", name).strip("_")
    name = re.sub(r"_+", "_", name)[:80]
    return name + suffix


def _detect_url_type(url: str) -> str:
    """Classify the URL for targeted extraction."""
    lower = url.lower()
    if "twitter.com" in lower or "x.com" in lower:
        return "tweet"
    if "github.com" in lower:
        return "github"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if any(path.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    return "webpage"


def _fetch_html(url: str) -> str:
    return safe_fetch_text(url)


def _html_to_markdown(html: str, url: str) -> str:
    """Convert HTML to clean markdown. Uses html2text if available, else basic strip."""
    try:
        import html2text

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0
        return h.handle(html)
    except ImportError:
        # Fallback: strip tags
        text = re.sub(
            r"<script[^>]*>.*?</script>", "", html, flags = re.DOTALL | re.IGNORECASE
        )
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", text, flags = re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


def _fetch_tweet(
    url: str, author: str | None, contributor: str | None
) -> tuple[str, str]:
    """Fetch a tweet URL via fxTwitter API (full text, no auth), fallback oEmbed."""
    # Extract screen name + tweet id for fxTwitter API
    match = re.search(
        r"(?:twitter\.com|x\.com)/(\w+)/status/(\d+)", url
    )
    tweet_text = ""
    tweet_author = "unknown"
    tweet_date = ""

    if match:
        screen_name = match.group(1)
        tweet_id = match.group(2)

        # Try fxTwitter first — returns full tweet text, no auth required
        try:
            fx_url = f"https://api.fxtwitter.com/{screen_name}/status/{tweet_id}"
            req = urllib.request.Request(
                fx_url, headers={"User-Agent": "graphify/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            tweet = data.get("tweet", {})
            tweet_text = (tweet.get("text") or "").strip()
            tweet_author = tweet.get("author", {}).get("name") or screen_name
            tweet_date = tweet.get("created_at") or ""
        except Exception as exc:
            logger.warning("fxTwitter fetch failed for %s: %s", url, exc)

    # Fallback to oEmbed (often truncated for longer tweets)
    if not tweet_text:
        try:
            oembed_url = url.replace("x.com", "twitter.com")
            oembed_api = (
                f"https://publish.twitter.com/oembed"
                f"?url={urllib.parse.quote(oembed_url)}&omit_script=true"
            )
            req = urllib.request.Request(
                oembed_api, headers={"User-Agent": "graphify/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            tweet_text = html.unescape(
                re.sub(r"<[^>]+>", "", data.get("html", "")).strip()
            )
            tweet_author = data.get("author_name", "unknown")
        except Exception as exc:
            logger.warning("oEmbed fetch failed for %s: %s", url, exc)
            tweet_text = f"Tweet at {url} (could not fetch content)"
            tweet_author = "unknown"

    now = datetime.now(timezone.utc).isoformat()
    content = f"""---
source_url: {url}
type: tweet
author: {tweet_author}
captured_at: {now}
contributor: {contributor or author or 'unknown'}
---

# Tweet by @{tweet_author}

{tweet_text}

Source: {url}
"""
    filename = _safe_filename(url, ".md")
    return content, filename


def _extract_youtube_id(url: str) -> str | None:
    """Extract YouTube video ID from youtube.com or youtu.be URLs."""
    # youtu.be/VIDEO_ID
    match = re.search(r"youtu\.be/([\w\-]{11})", url)
    if match:
        return match.group(1)
    # youtube.com/watch?v=VIDEO_ID
    parsed = urllib.parse.urlparse(url)
    if "youtube.com" in parsed.netloc:
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
    return None


def _fetch_youtube(
    url: str, author: str | None, contributor: str | None
) -> tuple[str, str]:
    """Fetch a YouTube video transcript via youtube-transcript-api."""
    video_id = _extract_youtube_id(url)
    if not video_id:
        return _fetch_webpage(url, author, contributor)

    # Get video title via oEmbed
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    title = video_id
    channel = "unknown"
    try:
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "graphify/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            title = data.get("title", video_id)
            channel = data.get("author_name", "unknown")
    except Exception as exc:
        logger.warning("YouTube oEmbed failed for %s: %s", url, exc)

    # Get transcript
    transcript_text = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        entries = api.fetch(video_id)
        transcript_text = "\n".join(
            f"[{e.start:.1f}s] {e.text}" for e in entries
        )
    except ImportError:
        logger.warning("youtube-transcript-api not installed, falling back to webpage")
        return _fetch_webpage(url, author, contributor)
    except Exception as exc:
        logger.warning("YouTube transcript fetch failed for %s: %s", url, exc)
        transcript_text = f"(Transcript unavailable: {exc})"

    now = datetime.now(timezone.utc).isoformat()
    content = f"""---
source_url: {url}
youtube_id: {video_id}
type: youtube
title: "{title}"
channel: "{channel}"
captured_at: {now}
contributor: {contributor or author or 'unknown'}
---

# {title}

Source: {url}

## Transcript

{transcript_text}
"""
    filename = f"youtube_{video_id}.md"
    return content, filename


def _fetch_webpage(
    url: str, author: str | None, contributor: str | None
) -> tuple[str, str]:
    """Fetch a generic webpage and convert to markdown."""
    html = _fetch_html(url)
    # Extract title
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
    )
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else url

    markdown = _html_to_markdown(html, url)
    now = datetime.now(timezone.utc).isoformat()
    content = f"""---
source_url: {url}
type: webpage
title: "{title}"
captured_at: {now}
contributor: {contributor or author or 'unknown'}
---

# {title}

Source: {url}

---

{markdown}
"""
    filename = _safe_filename(url, ".md")
    return content, filename


_PDF_MAGIC = b"%PDF"


def _download_binary(url: str, suffix: str, target_dir: Path) -> Path:
    """Download a binary file (PDF, image) directly."""
    filename = _safe_filename(url, suffix)
    out_path = target_dir / filename
    data = safe_fetch(url)

    if suffix == ".pdf" and not data.startswith(_PDF_MAGIC):
        preview = data[:512].decode("utf-8", errors="replace").strip()
        if re.search(r"<!DOCTYPE\s+html|<html", preview, re.IGNORECASE):
            raise RuntimeError(
                f"Expected PDF but received HTML from {url!r} "
                f"(likely paywall or login redirect)"
            )
        raise RuntimeError(
            f"Expected PDF but received unrecognized content from {url!r} "
            f"(starts with: {preview[:80]})"
        )

    out_path.write_bytes(data)
    return out_path


def ingest(
    url: str,
    target_dir: Path,
    author: str | None = None,
    contributor: str | None = None,
) -> Path:
    """
    Fetch a URL and save it into target_dir as a graphify-ready file.

    Returns the path of the saved file.
    """
    target_dir.mkdir(parents = True, exist_ok = True)
    url_type = _detect_url_type(url)

    try:
        url = validate_url(url)
    except ValueError as exc:
        raise ValueError(f"ingest: {exc}") from exc

    # Convert arxiv URLs to direct PDF downloads
    if "arxiv.org" in url.lower():
        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", url)
        if arxiv_match:
            url = f"https://arxiv.org/pdf/{arxiv_match.group(1)}.pdf"
            url_type = "pdf"

    try:
        if url_type == "pdf":
            out = _download_binary(url, ".pdf", target_dir)
            print(f"Downloaded PDF: {out.name}")
            return out

        if url_type == "image":
            suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
            out = _download_binary(url, suffix, target_dir)
            print(f"Downloaded image: {out.name}")
            return out

        if url_type == "tweet":
            content, filename = _fetch_tweet(url, author, contributor)
        elif url_type == "youtube":
            content, filename = _fetch_youtube(url, author, contributor)
        elif url_type == "github":
            content, filename = _fetch_webpage(url, author, contributor)
        else:
            content, filename = _fetch_webpage(url, author, contributor)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"ingest: failed to fetch {url!r}: {exc}") from exc

    out_path = target_dir / filename
    # Avoid overwriting - append counter if needed
    counter = 1
    while out_path.exists():
        stem = Path(filename).stem
        out_path = target_dir / f"{stem}_{counter}.md"
        counter += 1

    out_path.write_text(content, encoding = "utf-8")
    print(f"Saved {url_type}: {out_path.name}")
    return out_path


def save_query_result(
    question: str,
    answer: str,
    memory_dir: Path,
    query_type: str = "query",
    source_nodes: list[str] | None = None,
) -> Path:
    """Save a Q&A result as markdown so it gets extracted into the graph on next --update.

    Files are stored in memory_dir (typically graphify-out/memory/) with YAML frontmatter
    that graphify's extractor reads as node metadata. This closes the feedback loop:
    the system grows smarter from both what you add AND what you ask.
    """
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents = True, exist_ok = True)

    now = datetime.now(timezone.utc)
    slug = re.sub(r"[^\w]", "_", question.lower())[:50].strip("_")
    filename = f"query_{now.strftime('%Y%m%d_%H%M%S')}_{slug}.md"

    frontmatter_lines = [
        "---",
        f'type: "{query_type}"',
        f'date: "{now.isoformat()}"',
        f'question: "{re.sub(chr(10) + chr(13), " ", question).replace(chr(34), chr(39))}"',
        'contributor: "graphify"',
    ]
    if source_nodes:
        nodes_str = ", ".join(f'"{n}"' for n in source_nodes[:10])
        frontmatter_lines.append(f"source_nodes: [{nodes_str}]")
    frontmatter_lines.append("---")

    body_lines = [
        "",
        f"# Q: {question}",
        "",
        "## Answer",
        "",
        answer,
    ]
    if source_nodes:
        body_lines += ["", "## Source Nodes", ""]
        body_lines += [f"- {n}" for n in source_nodes]

    content = "\n".join(frontmatter_lines + body_lines)
    out_path = memory_dir / filename
    out_path.write_text(content, encoding = "utf-8")
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description = "Fetch a URL into a graphify /raw folder"
    )
    parser.add_argument("url", help = "URL to fetch")
    parser.add_argument(
        "target_dir",
        nargs = "?",
        default = "./raw",
        help = "Target directory (default: ./raw)",
    )
    parser.add_argument("--author", help = "Your name (stored as node metadata)")
    parser.add_argument("--contributor", help = "Contributor name for team graphs")
    args = parser.parse_args()
    out = ingest(
        args.url,
        Path(args.target_dir),
        author = args.author,
        contributor = args.contributor,
    )
    print(f"Ready for graphify: {out}")
