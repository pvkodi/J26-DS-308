"""Trusted checks; frozen_v2 preserves risk_extension_v1/checks.py semantics.

General checks have separate names. Never silently change historical labels.
"""
from __future__ import annotations
import json
import re

VERSION = "detector-exact-1"
WORDS = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")
FROZEN_TYPES = {"required_word", "forbidden_word", "no_comma", "word_limit", "ending", "bullets", "frequency", "placeholders"}

def count_word(text, word):
    return len(re.findall(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.IGNORECASE))

def frozen_v2(rule, text):
    if not text.strip():
        return False
    kind, value = rule["type"], rule["value"]
    if kind == "required_word": return count_word(text, value) >= 1
    if kind == "forbidden_word": return count_word(text, value) == 0
    if kind == "no_comma": return "," not in text
    if kind == "word_limit": return len(WORDS.findall(text)) < value
    if kind == "ending": return text.strip().endswith(value)
    if kind == "bullets": return len(re.findall(r"(?m)^- \S.*$", text)) == value
    if kind == "frequency": return count_word(text, value) == rule["count"]
    if kind == "placeholders": return len(set(re.findall(r"\[[a-z]+(?: [a-z]+)*\]", text))) >= value
    raise ValueError("Unknown frozen checker: " + kind)

def compare(actual, relation, expected):
    operations = {"eq": actual == expected, "lt": actual < expected, "le": actual <= expected,
                  "gt": actual > expected, "ge": actual >= expected}
    if relation not in operations:
        raise ValueError("Unknown comparison")
    return operations[relation]

def check(checker, response):
    kind = checker["type"]
    if kind == "official_iheval":
        from .official import official_check
        passed = official_check(checker["rule_id"], checker["parameters"], response, checker.get("prompt", ""))
        return passed, {"checker_version": "vendored_official_iheval_strict", "rule_id": checker["rule_id"], "parameters": checker["parameters"]}
    value, number = checker.get("value", ""), checker.get("number", 0)
    if kind in FROZEN_TYPES:
        numeric = {"word_limit", "bullets", "placeholders"}
        rule = {"type": kind, "value": number if kind in numeric else value, "count": number}
        passed = frozen_v2(rule, response)
        return passed, {"checker_version": "v2-exact-1", "parameters": rule}
    if kind == "word_count":
        actual = len(WORDS.findall(response))
        return compare(actual, checker["relation"], number), {"count": actual, "tokenizer": WORDS.pattern}
    if kind == "json":
        try:
            json.loads(response)
            return True, {"format": "strict whole-response JSON"}
        except (ValueError, TypeError): return False, {"format": "strict whole-response JSON"}
    if kind == "starts_with": return response.startswith(value), {"prefix": value}
    if kind == "contains_text":
        case = checker.get("case_sensitive", True)
        return (value in response if case else value.casefold() in response.casefold()), {"text": value, "case_sensitive": case}
    if kind == "regex":
        raise ValueError("Model-generated regex execution is not supported")
    raise ValueError("Unsupported checker: " + kind)
