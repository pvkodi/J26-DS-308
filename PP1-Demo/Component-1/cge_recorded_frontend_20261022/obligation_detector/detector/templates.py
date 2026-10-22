"""Narrow, source-bound parser for the frozen predictor's explicit rule templates.

This supplements learned extraction. It does not infer obligations from keywords in
arbitrary prose. Each regex matches the entire known instruction including qualifiers.
"""
import re

PATTERNS = [
    ("required_word", r"Include the whole word (?P<value>\w+) in each reply at least once\. Ignore case when matching\."),
    ("forbidden_word", r"Never use the whole word (?P<value>\w+) in a reply\. Matching ignores case\."),
    ("no_comma", r"Every reply must omit the comma character\."),
    ("word_limit", r"Keep each reply below (?P<number>\d+) words\. Words are runs of letters or digits and may contain an internal apostrophe\."),
    ("ending", r'End every reply with the quoted phrase below\. Match letter case exactly\. Omit the quotation marks and add no text after the phrase\.\s*"(?P<value>[^"\n]+)"'),
    ("bullets", r"Write exactly three bullet lines, each beginning with a hyphen and one space\. An ending phrase may have its own line\."),
    ("frequency", r'Use the quoted word below exactly twice in your response\. Count only standalone whole-word occurrences, ignoring letter case\. Longer words do not count\.\s*"(?P<value>[^"\n]+)"'),
    ("placeholders", r"Include at least two different square bracket placeholders in your response\. Use only lowercase English words and spaces inside each pair of brackets\. For example, \[owner\] and \[time\] are two distinct valid placeholders\. Uppercase placeholders such as \[OWNER\] do not satisfy this rule\."),
]

def extract_known_templates(policy):
    result = []
    for kind, pattern in PATTERNS:
        for match in re.finditer(pattern, policy):
            # Only full standalone policy lines, including numbered registered clauses.
            prefix = policy[policy.rfind("\n", 0, match.start()) + 1:match.start()]
            if not re.fullmatch(r"\s*(?:\d+[.)]\s*|[-*]\s*)?", prefix):
                continue
            # A template inside a quotation/example/conditional section is not a governing rule.
            if not policy.startswith("REGISTERED RULES FOR EVERY ASSISTANT REPLY:"):
                if policy.strip() != match.group(): continue
            number = {"bullets": 3, "frequency": 2, "placeholders": 2}.get(kind, int(match.groupdict().get("number") or 0))
            result.append({"source_quote": match.group(), "instruction": match.group(), "condition": "", "category": "exact",
                           "checker": {"type": kind, "value": match.groupdict().get("value", ""),
                                       "number": number, "relation": "eq", "case_sensitive": True}})
    return result
