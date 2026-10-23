"""Set-prediction metrics for multi-label instruction applicability."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from .data import Case


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def _counts(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    p, r = _safe_div(tp, tp + fp), _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * p * r, p + r)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def score_case(gold: Iterable[int], predicted: Iterable[int]) -> dict[str, float | int | bool]:
    g, p = set(gold), set(predicted)
    values = _counts(len(g & p), len(p - g), len(g - p))
    if not g and not p:
        values["precision"] = values["recall"] = values["f1"] = 1.0
    values["exact_set"] = p == g
    values["none_case"] = not g
    values["none_case_correct"] = (not p) if not g else False
    return values


def _aggregate(cases: Sequence[Case], predsets: Mapping[str, set[int]]) -> dict:
    tp = fp = fn = exact = none_n = none_ok = 0
    nonempty_f1s: list[float] = []
    all_f1s: list[float] = []
    dialogue: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for case in cases:
        pred = predsets[case.example_id]
        s = score_case(case.gold_indices, pred)
        tp += int(s["tp"]); fp += int(s["fp"]); fn += int(s["fn"])
        exact += int(s["exact_set"])
        all_f1s.append(float(s["f1"]))
        if case.gold_indices:
            nonempty_f1s.append(float(s["f1"]))
        else:
            none_n += 1
            none_ok += int(s["none_case_correct"])
        dialogue_key = case.dialogue_id or f"__missing_dialogue__:{case.example_id}"
        dialogue[dialogue_key].append((float(s["f1"]), bool(s["exact_set"])))

    fp_empty = sum(len(predsets[c.example_id]) for c in cases if not c.gold_indices)
    empty_error_cases = sum(bool(predsets[c.example_id]) for c in cases if not c.gold_indices)
    result = _counts(tp, fp, fn)
    result.update({
        "examples": len(cases),
        "example_macro_f1": _safe_div(sum(all_f1s), len(all_f1s)),
        "nonempty_gold_macro_f1": _safe_div(sum(nonempty_f1s), len(nonempty_f1s)),
        "nonempty_gold_count": len(nonempty_f1s),
        "exact_set_accuracy": _safe_div(exact, len(cases)),
        "exact_set_correct": exact,
        "none_case_accuracy": _safe_div(none_ok, none_n),
        "none_case_count": none_n,
        "empty_case_false_positive_count": fp_empty,
        "empty_case_false_positive_case_count": empty_error_cases,
        "empty_case_false_positive_fraction": _safe_div(empty_error_cases, none_n),
        "by_dialogue_macro_f1": _safe_div(sum(sum(x[0] for x in vals) / len(vals) for vals in dialogue.values()), len(dialogue)),
        "by_dialogue_macro_exact_set_accuracy": _safe_div(sum(sum(1 for x in vals if x[1]) / len(vals) for vals in dialogue.values()), len(dialogue)),
        "dialogue_count": len(dialogue),
    })
    return result


def evaluate(cases: Sequence[Case], predictions: Mapping[str, Iterable[int]]) -> dict:
    """Evaluate index sets, requiring exactly one output per unique example."""
    if not cases:
        raise ValueError("evaluation cohort must not be empty")
    expected = [c.example_id for c in cases]
    if len(expected) != len(set(expected)) or any(not x for x in expected):
        raise ValueError("cases must have unique, nonempty example IDs")
    if set(predictions) != set(expected):
        missing, unknown = set(expected) - set(predictions), set(predictions) - set(expected)
        raise ValueError(f"prediction keys must match examples exactly (missing={sorted(missing)}, unknown={sorted(unknown)})")
    predsets: dict[str, set[int]] = {}
    for case in cases:
        raw = list(predictions[case.example_id])
        if len(raw) != len(set(raw)):
            raise ValueError(f"duplicate predicted candidate index for {case.example_id}")
        if any(type(i) is not int or i < 0 or i >= len(case.instructions) for i in raw):
            raise ValueError(f"prediction index out of range for {case.example_id}")
        predsets[case.example_id] = set(raw)
    result = _aggregate(cases, predsets)
    by_type: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_type[c.example_type].append(c)
    result["by_type"] = {k: _aggregate(v, predsets) for k, v in sorted(by_type.items())}
    return result
