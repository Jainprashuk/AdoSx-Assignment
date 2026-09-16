"""
Reading the dirty cells: numbers, dates, and record references.

Every function here is total. Nothing raises on bad input; a value that cannot
be read comes back as None with a human-readable reason, and the caller decides
what to do with it. That contract is what lets the importer keep a row whose
cells it could not parse instead of dropping it.

Imports nothing from Django, so it can be read and tested on its own.

What it deliberately does not do: guess at date formats other than ISO, or
repair a number beyond removing grouping separators. Inventing an
interpretation for text nobody can read is worse than reporting it.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

# Bare digits in a reference get this prefix. Justified by the data, not by
# taste: every record identifier in system_a.csv is REC- followed by four
# digits, so a system B reference of "1112" has exactly one possible meaning.
# Leaving it unmatched would report a false orphan, which is a wrong answer
# dressed up as a cautious one.
DEFAULT_REF_PREFIX = "REC"

# Grouping separators, stripped before parsing. Covers both the Western
# 125,400.00 and the Indian 1,25,400.00 in system_b.csv line 63, because the
# rule is "commas do not carry meaning here", not "commas appear every three
# digits". The decimal point is left alone.
_GROUPING = str.maketrans("", "", ",  _")

# A reference reduced to letters and digits, e.g. REC1034 -> ("REC", "1034").
_REF_SHAPE = re.compile(r"([A-Z]*)(\d+)")

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def parse_decimal(raw: str | None) -> tuple[Decimal | None, str | None]:
    """Read a money value.

    Returns (value, problem). Exactly one of the two is meaningful:

        ("88969.92",)   -> (Decimal("88969.92"), None)
        ("1,25,400.00") -> (Decimal("125400.00"), None)
        ("")            -> (None, None)      blank is not a problem
        ("N/A")         -> (None, "not a number: 'N/A'")

    A blank cell returns no problem because an empty field is an absence, not a
    failure. The caller distinguishes the two by keeping the raw text: no value
    and no raw text means the source said nothing; no value with raw text means
    the source said something unreadable.
    """
    if raw is None:
        return None, None
    text = raw.strip()
    if not text:
        return None, None

    try:
        value = Decimal(text.translate(_GROUPING))
    except InvalidOperation:
        return None, f"not a number: {text!r}"

    # Decimal accepts "NaN" and "Infinity" as valid literals. They parse without
    # raising and then poison every comparison they touch, so they are rejected
    # here rather than stored as if they were amounts.
    if not value.is_finite():
        return None, f"not a finite number: {text!r}"

    return value, None


def parse_date(raw: str | None) -> tuple[date | None, str | None]:
    """Read an ISO date (YYYY-MM-DD).

    Returns (value, problem), same contract as parse_decimal: a blank cell is
    (None, None), anything unreadable is (None, reason).

    ISO only. Every date in both source files is already ISO, and guessing
    between 03-04-2026 and 04-03-2026 would silently invent a fact. A file that
    arrives in another format should fail visibly here and be handled
    deliberately, not be absorbed by a parser that quietly picks an ordering.
    """
    if raw is None:
        return None, None
    text = raw.strip()
    if not text:
        return None, None

    match = _ISO_DATE.fullmatch(text)
    if not match:
        return None, f"not an ISO date: {text!r}"

    year, month, day = (int(part) for part in match.groups())
    try:
        # Catches 2026-02-30, which matches the pattern but is not a day.
        return date(year, month, day), None
    except ValueError as exc:
        return None, f"not a real date: {text!r} ({exc})"


def normalize_ref(raw: str | None) -> str:
    """Reduce a record reference to the form used for matching.

    The same record is written three ways across system_b.csv:

        "REC-1034"      -> "REC-1034"
        "rec1034"       -> "REC-1034"
        " REC - 1070 "  -> "REC-1070"
        "1112"          -> "REC-1112"
        ""              -> ""

    Returns the normalised string, never None. An empty input gives an empty
    string, which matches no record and so surfaces as a finding rather than
    matching everything.

    The normalisation is deliberately narrow: case, surrounding and embedded
    whitespace, and separator style. It does not correct digits or guess at
    near-misses. REC-1999 stays REC-1999 and is reported as pointing at nothing,
    because a reference that is merely close to a real record is not the same
    fact as one written untidily.
    """
    if raw is None:
        return ""

    # Strip everything that is not a letter or digit: this collapses the
    # separator question ("-", " - ", none at all) into one shape.
    compact = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if not compact:
        return ""

    match = _REF_SHAPE.fullmatch(compact)
    if not match:
        # An unexpected shape (letters after digits, letters only). Returned
        # uppercased and compacted rather than discarded, so it can still be
        # displayed and reported instead of vanishing.
        return compact

    prefix, digits = match.groups()
    return f"{prefix or DEFAULT_REF_PREFIX}-{digits}"
