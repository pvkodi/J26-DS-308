"""V2 checker semantics, deliberately independent of the old model environment."""
from __future__ import annotations

import re

VERSION = "v2-exact-1"
WORDS = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def word_count(text):
    return len(WORDS.findall(text))


def count_word(text, word):
    return len(re.findall(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.IGNORECASE))


def check(rule, text):
    if not text.strip():
        return False
    kind, value = rule["type"], rule["value"]
    if kind == "required_word":
        return count_word(text, value) >= 1
    if kind == "forbidden_word":
        return count_word(text, value) == 0
    if kind == "no_comma":
        return "," not in text
    if kind == "word_limit":
        return word_count(text) < value
    if kind == "ending":
        return text.strip().endswith(value)
    if kind == "bullets":
        return len(re.findall(r"(?m)^- \S.*$", text)) == value
    if kind == "frequency":
        return count_word(text, value) == rule["count"]
    if kind == "placeholders":
        return len(set(re.findall(r"\[[a-z]+(?: [a-z]+)*\]", text))) >= value
    raise ValueError("Unknown checker: " + kind)


def verify(rules, text):
    return [dict(id=r["id"], type=r["type"], passed=check(r, text), checker_version=VERSION) for r in rules]


def witness(scenario):
    return (f"- {scenario['keyword']} {scenario['frequency']} [owner]\n"
            f"- {scenario['frequency']} [time]\n- Confirm the next action\n{scenario['ending']}")
