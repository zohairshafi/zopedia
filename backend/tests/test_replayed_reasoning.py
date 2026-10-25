"""Replayed reasoning must not smuggle old instructions back to the model.

CHAT_SYNTHESIS_PROMPT ("DO NOT use any more tools") is injected as a user message
for the final-answer phase of a turn. The model's reasoning for that turn quotes
it, the client stores that reasoning inside the assistant message and replays it
as `reasoning_content` on the next turn — so from turn five or six onward the
model is reading its own past thinking as a standing instruction from the user,
and stops calling tools.

Checked against the real history before writing this (80 threads, 904 messages):
every stale copy of the instruction was inside a `reasoning` part, never in
message text. Dropping the field is therefore a complete fix for this leak.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.chat import _strip_replayed_reasoning  # noqa: E402
from prompts import CHAT_SYNTHESIS_PROMPT  # noqa: E402


def _history_with_quoted_instruction() -> list[dict]:
    """The shape actually found in the stored history."""
    return [
        {"role": "user", "content": "What drove oil prices this week?"},
        {
            "role": "assistant",
            "content": "Here is the answer.",
            "reasoning_content": (
                "The user's last message: \"Now synthesize a complete, thorough answer "
                "using all the wiki pages ... " + CHAT_SYNTHESIS_PROMPT + "\" "
                "This seems like a generic instruction, but the user is still asking "
                "about the paper."
            ),
        },
    ]


def test_quoted_instruction_does_not_survive_into_the_next_turn():
    history = _history_with_quoted_instruction()

    out = _strip_replayed_reasoning(history)

    assert all("reasoning_content" not in m for m in out)
    blob = " ".join(str(m.get("content", "")) for m in out)
    assert "DO NOT use any more tools" not in blob


def test_message_content_is_preserved():
    history = _history_with_quoted_instruction()
    out = _strip_replayed_reasoning(history)
    assert out[0]["content"] == "What drove oil prices this week?"
    assert out[1]["content"] == "Here is the answer."


def test_no_reasoning_is_a_no_op():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    before = [dict(m) for m in history]
    assert _strip_replayed_reasoning(history) == before


def test_other_fields_survive():
    history = [
        {
            "role": "assistant",
            "content": "done",
            "reasoning_content": "thinking",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "search_wiki"}}],
        }
    ]
    out = _strip_replayed_reasoning(history)
    assert out[0]["tool_calls"][0]["function"]["name"] == "search_wiki"
    assert "reasoning_content" not in out[0]


@pytest.mark.parametrize("role", ["user", "system", "tool"])
def test_non_assistant_messages_are_untouched(role):
    history = [{"role": role, "content": "x", "reasoning_content": "keep"}]
    assert _strip_replayed_reasoning(history)[0]["reasoning_content"] == "keep"
