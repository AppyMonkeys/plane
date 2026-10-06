# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
A small subset of Jira's JQL, enough for tools written against Jira's search API to run against
Plane (see plane/api/views/jira_compat.py).

Supported: clauses joined by AND, each one of

    field = value | field != value
    field IN (a, b) | field NOT IN (a, b)
    field IS EMPTY | field IS NOT EMPTY
    field ~ "text"
    field >= value   (also > <= <; dates only)

optionally followed by `ORDER BY field [ASC|DESC], ...`. Values may be quoted, a function call such
as currentUser(), or a relative date such as -30m / -2h / -7d / -1w. OR and parentheses around
clauses are not supported and raise JQLError.
"""

# Python imports
import re
from dataclasses import dataclass, field


class JQLError(ValueError):
    """The JQL is malformed or uses something outside the supported subset."""


@dataclass
class Clause:
    field: str  # lower-cased
    operator: str  # one of = != in not in is is not ~ >= > <= <
    values: list  # strings, with quotes removed


@dataclass
class Query:
    clauses: list = field(default_factory=list)
    order_by: list = field(default_factory=list)  # [(field, descending)]


ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)
CLAUSE_RE = re.compile(
    r"""^\s*
    (?P<field>[A-Za-z_][\w.]*|"[^"]+")\s*
    (?P<operator>not\s+in\b|is\s+not\b|in\b|is\b|!=|>=|<=|=|~|>|<)\s*
    (?P<value>.+?)\s*$""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def split_outside_quotes(text, separator_re):
    """Split on a regex, ignoring matches inside quotes or parentheses."""
    parts, current, depth, quote, index = [], [], 0, None, 0
    while index < len(text):
        char = text[index]
        if quote:
            current.append(char)
            if char == "\\" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 1
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        else:
            match = separator_re.match(text, index) if depth == 0 else None
            if match:
                parts.append("".join(current))
                current = []
                index = match.end()
                continue
            current.append(char)
        index += 1
    if quote or depth != 0:
        raise JQLError("Unbalanced quotes or parentheses in JQL")
    parts.append("".join(current))
    return parts


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
OR_RE = re.compile(r"\s+or\s+", re.IGNORECASE)
COMMA_RE = re.compile(r"\s*,\s*")


def parse_jql(jql):
    jql = (jql or "").strip()
    query = Query()

    order_parts = split_outside_quotes(jql, ORDER_BY_RE)
    if len(order_parts) > 2:
        raise JQLError("JQL may contain only one ORDER BY")
    where = order_parts[0].strip()

    if len(order_parts) == 2:
        for item in split_outside_quotes(order_parts[1], COMMA_RE):
            tokens = item.split()
            if not tokens or len(tokens) > 2:
                raise JQLError(f"Cannot read ORDER BY '{item.strip()}'")
            direction = tokens[1].lower() if len(tokens) == 2 else "asc"
            if direction not in ("asc", "desc"):
                raise JQLError(f"Cannot read ORDER BY '{item.strip()}'")
            query.order_by.append((unquote(tokens[0]).lower(), direction == "desc"))

    if not where:
        return query

    if len(split_outside_quotes(where, OR_RE)) > 1:
        raise JQLError("OR is not supported; only AND between clauses")

    for raw_clause in split_outside_quotes(where, AND_RE):
        text = raw_clause.strip()
        if text.startswith("("):
            raise JQLError("Parentheses around clauses are not supported")
        match = CLAUSE_RE.match(text)
        if not match:
            raise JQLError(f"Cannot read JQL clause '{text}'")

        operator = re.sub(r"\s+", " ", match.group("operator").lower())
        value = match.group("value").strip()

        if operator in ("in", "not in"):
            if not (value.startswith("(") and value.endswith(")")):
                raise JQLError(f"Expected a list in parentheses after {operator.upper()} in '{text}'")
            values = [unquote(item) for item in split_outside_quotes(value[1:-1], COMMA_RE) if item.strip()]
        elif operator in ("is", "is not"):
            if value.lower() not in ("empty", "null"):
                raise JQLError(f"Only EMPTY or NULL can follow IS in '{text}'")
            values = []
        else:
            values = [unquote(value)]

        query.clauses.append(Clause(field=unquote(match.group("field")).lower(), operator=operator, values=values))

    return query
