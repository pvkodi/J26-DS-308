"""Product wrapper for turning selected instructions into exact reminders.

The caller supplies the complete trusted instruction list and the original
prompt. This wrapper only decides which supplied blocks to append; it does not
split, rewrite, or assign meaning to instructions. Token-prefix compatibility
must be established by an explicit token-ID verification by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .data import Case, Instruction
from .encoder import UnsupportedInput
from .renderer import assert_prefix_preserved, render_reminder


@dataclass(frozen=True)
class ReminderResult:
    original: str
    result_text: str
    selected_ids: tuple[str, ...]
    selected_texts: tuple[str, ...]
    scores: Mapping[str, float]
    status: str
    cache_verified: bool = False
    reason: str | None = None


class ReminderOptimizer:
    """Apply a loaded CPUSelector to one prompt and its full instruction list."""

    def __init__(self, selector):
        self.selector = selector

    def optimize(
        self,
        context: str,
        instructions: Sequence[Instruction],
        original: str,
        max_added_tokens: int | None = None,
        token_counter: Callable[[str], int] | None = None,
    ) -> ReminderResult:
        if not isinstance(context, str):
            raise TypeError("context must be a string")
        if not isinstance(original, str):
            raise TypeError("original must be a string")
        instructions = tuple(instructions)
        _validate_instructions(instructions)
        # Validate budget arguments before any model work, including abstentions.
        render_reminder(original, instructions, (), token_counter, max_added_tokens)

        if not instructions:
            return ReminderResult(original, original, (), (), {}, "no_instructions", False)

        # Stable within this one-case API call; it is not a feature or label.
        case = Case("reminder_optimizer_case", context, instructions, ())
        try:
            predictions, raw_scores = self.selector.predict((case,))
        except UnsupportedInput as exc:
            return ReminderResult(original, original, (), (), {}, "unsupported_input", False, str(exc))

        if set(predictions) != {case.example_id} or set(raw_scores) != {case.example_id}:
            raise ValueError("selector output keys do not match the inference case")
        indices = list(predictions[case.example_id])
        if len(indices) != len(set(indices)) or any(type(i) is not int or i < 0 or i >= len(instructions) for i in indices):
            raise ValueError("selector returned duplicate or out-of-range candidate indices")
        candidate_scores = list(raw_scores[case.example_id])
        if len(candidate_scores) != len(instructions):
            raise ValueError("selector returned a score count that does not match the instruction list")
        scores = {instruction.id: float(candidate_scores[i]) for i, instruction in enumerate(instructions)}
        selected_ids = tuple(instructions[i].id for i in indices)
        selected_texts = tuple(instructions[i].text for i in indices)
        rendered = render_reminder(original, instructions, selected_ids, token_counter, max_added_tokens)
        return ReminderResult(original, rendered.text, selected_ids, selected_texts, scores,
                              rendered.status, False)


def _validate_instructions(instructions: Sequence[Instruction]) -> None:
    ids: set[str] = set()
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, Instruction):
            raise TypeError(f"instruction at index {index} must be an Instruction")
        if not isinstance(instruction.id, str) or not instruction.id:
            raise ValueError(f"instruction at index {index} has an empty or invalid ID")
        if instruction.id in ids:
            raise ValueError(f"duplicate instruction ID {instruction.id!r}")
        ids.add(instruction.id)
        if not isinstance(instruction.text, str) or not instruction.text.strip():
            raise ValueError(f"instruction {instruction.id!r} has empty or invalid text")


def verify_token_prefix(before_ids: Sequence[int], after_ids: Sequence[int], boundary: int) -> None:
    """Explicitly verify token IDs through a caller-chosen cache boundary."""
    assert_prefix_preserved(before_ids, after_ids, boundary)
