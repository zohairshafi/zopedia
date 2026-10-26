"""The image field must actually reach the upstream request.

Clients send `image_base64` next to `messages`, whose content is text-only. The
chat endpoint used to ignore the field entirely, so every image attachment was
silently dropped — the web client included. These tests pin the conversion to the
OpenAI multimodal shape the upstream API accepts (verified against
api.deepseek.com: an image_url part returns 200 and counts image prompt tokens).
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.chat import _attach_image_to_last_user_message  # noqa: E402

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 16).decode()
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"x" * 16).decode()


def test_text_content_becomes_multimodal():
    messages = [{"role": "user", "content": "What is this?"}]

    _attach_image_to_last_user_message(messages, JPEG)

    content = messages[0]["content"]
    assert content[0] == {"type": "text", "text": "What is this?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == f"data:image/jpeg;base64,{JPEG}"


def test_raw_png_is_labelled_png():
    messages = [{"role": "user", "content": "x"}]

    _attach_image_to_last_user_message(messages, PNG)

    url = messages[0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_data_url_keeps_its_mime_and_is_not_double_wrapped():
    messages = [{"role": "user", "content": "x"}]

    _attach_image_to_last_user_message(messages, f"data:image/webp;base64,{JPEG}")

    url = messages[0]["content"][1]["image_url"]["url"]
    assert url == f"data:image/webp;base64,{JPEG}"


def test_only_the_last_user_message_is_modified():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]

    _attach_image_to_last_user_message(messages, JPEG)

    assert messages[0]["content"] == "first"
    assert isinstance(messages[2]["content"], list)


def test_existing_multimodal_content_is_untouched():
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "x"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}},
        ],
    }]
    before = [dict(m) for m in messages]

    _attach_image_to_last_user_message(messages, JPEG)

    assert messages == before


def test_no_image_is_a_no_op():
    messages = [{"role": "user", "content": "x"}]

    _attach_image_to_last_user_message(messages, "")
    _attach_image_to_last_user_message(messages, None)

    assert messages[0]["content"] == "x"


def test_no_user_message_is_a_no_op():
    messages = [{"role": "assistant", "content": "hi"}]

    _attach_image_to_last_user_message(messages, JPEG)

    assert messages[0]["content"] == "hi"


def test_list_text_parts_are_flattened():
    messages = [{
        "role": "user",
        "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
    }]

    _attach_image_to_last_user_message(messages, JPEG)

    assert messages[0]["content"][0] == {"type": "text", "text": "a b"}
