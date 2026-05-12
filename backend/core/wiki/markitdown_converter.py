"""Thin wrapper around Microsoft MarkItDown for unified file-to-markdown conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_markitdown_instance: Optional["MarkItDown"] = None


def _get_markitdown() -> "MarkItDown":
    global _markitdown_instance
    if _markitdown_instance is not None:
        return _markitdown_instance

    from markitdown import MarkItDown

    llm_client = None
    llm_model = None
    try:
        from core.llm import _LLM_BASE_URL, _LLM_API_KEY, _LLM_MODEL

        if _LLM_BASE_URL and _LLM_API_KEY:
            from openai import OpenAI

            base = _LLM_BASE_URL.rstrip("/")
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            llm_client = OpenAI(base_url=base, api_key=_LLM_API_KEY)
            llm_model = _LLM_MODEL
    except ImportError:
        logger.info("openai SDK not installed — MarkItDown will skip image/audio LLM features")
    except Exception as exc:
        logger.warning("Failed to create OpenAI client for MarkItDown: %s", exc)

    _markitdown_instance = MarkItDown(
        llm_client=llm_client,
        llm_model=llm_model,
    )
    return _markitdown_instance


def convert_file(file_path: Path) -> str:
    """Convert any supported file to markdown text using MarkItDown.

    Raises FileConversionException or UnsupportedFormatException on failure.
    """
    md = _get_markitdown()
    result = md.convert_local(str(file_path))
    return result.text_content.strip()
