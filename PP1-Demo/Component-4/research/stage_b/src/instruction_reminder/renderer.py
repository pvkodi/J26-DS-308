"""Exact-text reminder rendering and optional cache-prefix verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .data import Instruction


HEADER = "Instruction reminders (original wording):\n"


@dataclass(frozen=True)
class RenderResult:
    text: str
    status: str
    cache_verified: bool = False


def assert_prefix_preserved(before_ids: Sequence[int], after_ids: Sequence[int], boundary: int) -> None:
    """Raise unless token IDs before the declared boundary remain identical."""
    if boundary < 0 or boundary > len(before_ids) or boundary > len(after_ids):
        raise ValueError("boundary is outside token sequences")
    if list(before_ids[:boundary]) != list(after_ids[:boundary]):
        raise ValueError("token prefix changed before the declared cache boundary")


def render_reminder(
    original: str,
    instructions: Sequence[Instruction],
    selected_ids: Iterable[str],
    token_counter: Callable[[str], int] | None = None,
    max_added_tokens: int | None = None,
) -> RenderResult:
    """Append selected exact instructions; budget overflow abstains entirely.

    A caller-provided counter is required for token budgets. This routine does
    not imply that text concatenation preserves a model's token/KV prefix.
    """
    if max_added_tokens is not None and max_added_tokens < 0:
        raise ValueError("max_added_tokens must be nonnegative")
    if max_added_tokens is not None and token_counter is None:
        raise ValueError("token_counter is required when max_added_tokens is set")
    selected = list(selected_ids)
    if len(selected) != len(set(selected)):
        raise ValueError("selected_ids contains duplicates")
    chosen = set(selected)
    ids = [i.id for i in instructions]
    if len(ids) != len(set(ids)):
        raise ValueError("instruction IDs must be unique within the provided list")
    known = set(ids)
    unknown = chosen - known
    if unknown:
        raise ValueError(f"unknown selected instruction IDs: {sorted(unknown)!r}")
    if not chosen:
        return RenderResult(original, "no_selection")
    selected = [i.text for i in instructions if i.id in chosen]
    addition = HEADER + "\n".join(f"- {text}" for text in selected)
    separator = "" if not original or original.endswith(("\n", " ", "\t")) else "\n"
    added_text = separator + addition
    if max_added_tokens is not None and token_counter is not None and token_counter(added_text) > max_added_tokens:
        return RenderResult(original, "budget_abstain")
    return RenderResult(original + added_text, "rendered", cache_verified=False)
