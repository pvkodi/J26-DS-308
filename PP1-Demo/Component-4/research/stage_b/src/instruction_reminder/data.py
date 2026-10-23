"""Strict loader for NLSI's native per-example instruction lists."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class Instruction:
    """An instruction and its ID, which is local to its source example."""

    id: str
    text: str


@dataclass(frozen=True)
class Case:
    example_id: str
    context: str
    instructions: tuple[Instruction, ...]
    gold_indices: tuple[int, ...]
    dialogue_id: str = ""
    example_type: str = ""

    def model_input(self) -> dict[str, Any]:
        """Return model-visible content only; labels and metadata are excluded."""
        return {
            "context": self.context,
            "instructions": tuple(i.text for i in self.instructions),
        }


def parse_row(row: Mapping[str, Any]) -> Case:
    """Parse one serialized record, matching labels by exact text, never ID."""
    try:
        context = row["user_utterance"]
        raw_all = row["all_standing_instructions"]
        raw_gold = row["applicable_standing_instructions"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"row missing required field {exc}") from exc
    if not isinstance(context, str) or not isinstance(raw_all, list) or not isinstance(raw_gold, list):
        raise ValueError("user_utterance and instruction collections have invalid types")
    if not raw_all:
        raise ValueError("candidate instruction list must not be empty")

    instructions: list[Instruction] = []
    by_text: dict[str, int] = {}
    ids: set[str] = set()
    for idx, item in enumerate(raw_all):
        if not isinstance(item, Mapping) or not isinstance(item.get("nl_instruction"), str):
            raise ValueError(f"candidate at index {idx} has no string nl_instruction")
        text = item["nl_instruction"]
        if text in by_text:
            raise ValueError(f"duplicate candidate instruction text at indices {by_text[text]} and {idx}")
        if "instruction_id" not in item:
            raise ValueError(f"candidate at index {idx} has no native instruction_id")
        native_id = str(item["instruction_id"])
        if not native_id:
            raise ValueError(f"candidate at index {idx} has empty native instruction_id")
        if native_id in ids:
            raise ValueError(f"duplicate candidate native instruction_id {native_id!r}")
        ids.add(native_id)
        by_text[text] = idx
        instructions.append(Instruction(native_id, text))

    gold_indices: list[int] = []
    gold_seen: set[str] = set()
    for idx, item in enumerate(raw_gold):
        if not isinstance(item, Mapping) or not isinstance(item.get("nl_instruction"), str):
            raise ValueError(f"gold instruction at index {idx} has no string nl_instruction")
        text = item["nl_instruction"]
        if text in gold_seen:
            raise ValueError(f"duplicate gold instruction text at index {idx}")
        gold_seen.add(text)
        if text not in by_text:
            raise ValueError(f"gold instruction is absent from candidate list: {text!r}")
        gold_indices.append(by_text[text])

    metadata = row.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be an object")
    example_id = str(row.get("example_id", metadata.get("example_id", "")))
    if not example_id:
        raise ValueError("example_id must not be empty")
    return Case(
        example_id=example_id,
        context=context,
        instructions=tuple(instructions),
        gold_indices=tuple(sorted(gold_indices)),
        dialogue_id=str(metadata.get("dialogue_id", "")),
        example_type=str(metadata.get("example_type", "")),
    )


def load_jsonl(path: str | Path) -> list[Case]:
    """Load and validate a JSONL split in file order."""
    cases: list[Case] = []
    seen_example_ids: set[str] = set()
    with Path(path).open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_no}: {exc}") from exc
            if not isinstance(row, Mapping):
                raise ValueError(f"expected object at {path}:{line_no}")
            try:
                case = parse_row(row)
                if case.example_id in seen_example_ids:
                    raise ValueError(f"duplicate example_id {case.example_id!r}")
                seen_example_ids.add(case.example_id)
                cases.append(case)
            except ValueError as exc:
                raise ValueError(f"invalid row at {path}:{line_no}: {exc}") from exc
    return cases
