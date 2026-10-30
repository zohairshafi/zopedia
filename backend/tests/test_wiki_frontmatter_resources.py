"""Frontmatter resource merging must survive non-ASCII and backslash titles."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.wiki.engine import LLMWikiEngine  # noqa: E402


def merge(md: str, new_resources: list[str]) -> str:
    # Only the merge helpers are needed, so skip the engine's full setup.
    engine = object.__new__(LLMWikiEngine)
    return engine._merge_frontmatter_resources(md, new_resources)


def resources_of(md: str) -> list[str]:
    front = md.split("---", 2)[1]
    return yaml.safe_load(front)["resources"]


def test_merge_handles_unicode_escaped_titles():
    md = '---\ntitle: "Page"\nresources: ["a.md"]\n---\n\nBody.\n'
    title = 'Bravos Research Titled "Yep… It’s Happening AGAIN."'

    merged = merge(md, [title])

    assert resources_of(merged) == ["a.md", title]
    assert "Body." in merged


def test_merge_handles_backslash_digit_titles():
    md = "---\ntitle: Page\n---\n\nBody.\n"
    title = r"Version \1 draft"

    merged = merge(md, [title])

    assert resources_of(merged) == [title]
