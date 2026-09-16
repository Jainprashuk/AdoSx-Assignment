"""
Deciding where the two systems disagree.

Pure functions over plain dataclasses: no Django, no database, no I/O. The
caller loads rows and hands them over; this module only decides. That is what
makes the rules testable without fixtures and readable without the rest of the
app.

The brief requires four detections. There are six reasons here: the four, plus
UNCOMPARABLE for a pair that cannot be compared at all, plus CROSS_ORG_ENTRY
for an entry filed against another org's record. The last two are argued in
docs/DECISIONS.md, entries 12 and 13.

One record produces at most one finding. The alternative -- a row per rule
violated -- double-counts the same problem and makes "how many disagreements"
unanswerable, which is the number the screen leads with.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# A record in system A with no entry in system B.
MISSING_IN_B = "MISSING_IN_B"
# An entry in system B pointing at a record that does not exist in system A.
ORPHAN_ENTRY = "ORPHAN_ENTRY"
# The same record entered into system B more than once.
DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
# Both systems have the record and report different values.
VALUE_MISMATCH = "VALUE_MISMATCH"
# One side's value could not be read or was never given.
UNCOMPARABLE = "UNCOMPARABLE"
# The entry's location belongs to a different org than the record's.
CROSS_ORG_ENTRY = "CROSS_ORG_ENTRY"

# Order matters: it is the precedence used when a pair breaks more than one
# rule, and the order the reasons are listed in. Most structural first --
# "there is no entry" has to be decided before "the values differ" can mean
# anything.
REASONS = (
    MISSING_IN_B,
    ORPHAN_ENTRY,
    DUPLICATE_ENTRY,
    VALUE_MISMATCH,
    UNCOMPARABLE,
    CROSS_ORG_ENTRY,
)

# Money is compared at two decimal places, the scale both files are written in.
CENTS = Decimal("0.01")


def _quantise(value: Decimal) -> Decimal:
    """Round to two places for comparison.

    Decimal already treats 100.50 and 100.500 as equal, so this is not what
    makes trailing zeros a non-issue. It is here so that two values agreeing to
    the cent are not reported as a disagreement because of a third decimal
    place neither system displays.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RecordRow:
    """One system A record, as the comparison needs it."""

    key: str                    # normalised record_id, the match key
    record_id: str              # as written in the file
    value: Decimal | None       # total_value, None if blank or unreadable
    value_raw: str              # the original text, which says which of those it is
    location_code: str
    org_code: str | None        # None when the location was not in the mapping
    source_line: int
    state: str = ""


@dataclass(frozen=True)
class EntryRow:
    """One system B entry, as the comparison needs it."""

    entry_id: str
    key: str                    # normalised record_ref
    record_ref: str             # as written in the file
    value: Decimal | None
    value_raw: str
    location_code: str
    org_code: str | None
    source_line: int
    label: str = ""


@dataclass(frozen=True)
class Disagreement:
    """One row of the screen: what disagrees, and everything needed to judge it."""

    reason: str
    key: str
    record_id: str | None       # None for an orphan: there is no record
    org_code: str | None        # whose view this belongs in
    location_code: str
    a_value: Decimal | None
    a_value_raw: str
    b_value: Decimal | None
    b_value_raw: str
    entry_ids: tuple[str, ...]
    detail: str                 # one line a human can act on
    source_lines: tuple[int, ...] = ()

    @property
    def difference(self) -> Decimal | None:
        """A minus B, or None when one side has no comparable value."""
        if self.a_value is None or self.b_value is None:
            return None
        return self.a_value - self.b_value


def _unreadable(value: Decimal | None, raw: str) -> bool:
    """True when the source said something that could not be read.

    The paired columns carry the distinction the schema exists for: no value
    with text behind it is unreadable; no value with nothing behind it is
    absent. Both block comparison, and they are described differently because
    they are different facts about the export.
    """
    return value is None and raw.strip() != ""


def _describe_missing(value: Decimal | None, raw: str, side: str) -> str:
    if value is not None:
        return ""
    if raw.strip():
        return f"{side} value {raw.strip()!r} could not be read as a number"
    return f"{side} recorded no value"


def compare(records: list[RecordRow], entries: list[EntryRow]) -> list[Disagreement]:
    """Find every disagreement between two sets of rows.

    Takes whatever rows it is given and compares them against each other; it
    does no scoping of its own. The caller is responsible for handing over a
    coherent set -- see services.py, which builds one org's view.

    Returns one Disagreement per problem, ordered by reason then by record.
    Records and entries that agree produce nothing.
    """
    entries_by_key: dict[str, list[EntryRow]] = {}
    for entry in entries:
        entries_by_key.setdefault(entry.key, []).append(entry)

    found: list[Disagreement] = []
    matched_keys: set[str] = set()

    for record in sorted(records, key=lambda r: r.key):
        # Matched on the normalised reference rather than a foreign key: an
        # entry pointing at a record that does not exist is a required finding,
        # so the relationship cannot be a database constraint.
        matches = entries_by_key.get(record.key, [])
        matched_keys.add(record.key)

        if not matches:
            found.append(_missing(record))
        elif len(matches) > 1:
            found.append(_duplicated(record, matches))
        else:
            finding = _compare_pair(record, matches[0])
            if finding is not None:
                found.append(finding)

    for key in sorted(entries_by_key):
        if key not in matched_keys:
            for entry in entries_by_key[key]:
                found.append(_orphan(entry))

    return sorted(found, key=lambda d: (REASONS.index(d.reason), d.key))


def _missing(record: RecordRow) -> Disagreement:
    return Disagreement(
        reason=MISSING_IN_B,
        key=record.key,
        record_id=record.record_id,
        org_code=record.org_code,
        location_code=record.location_code,
        a_value=record.value,
        a_value_raw=record.value_raw,
        b_value=None,
        b_value_raw="",
        entry_ids=(),
        detail="System A has this record; system B has no entry referencing it.",
        source_lines=(record.source_line,),
    )


def _orphan(entry: EntryRow) -> Disagreement:
    # The reference is shown as written, not as normalised: the reviewer needs
    # to see what the file actually said, not what was inferred from it.
    written = entry.record_ref.strip() or "(blank)"
    inferred = f" (read as {entry.key})" if entry.key and entry.key != written else ""
    return Disagreement(
        reason=ORPHAN_ENTRY,
        key=entry.key,
        record_id=None,
        # An orphan belongs to the org that filed it. There is no record to
        # take ownership from, and the entry is that org's problem to explain.
        org_code=entry.org_code,
        location_code=entry.location_code,
        a_value=None,
        a_value_raw="",
        b_value=entry.value,
        b_value_raw=entry.value_raw,
        entry_ids=(entry.entry_id,),
        detail=f"Entry references {written}{inferred}; system A has no such record.",
        source_lines=(entry.source_line,),
    )


def _duplicated(record: RecordRow, matches: list[EntryRow]) -> Disagreement:
    """One finding for a record entered more than once, whatever the values.

    The detail says whether the entries agree with each other and whether they
    sum to system A's total, because those are the two things a human needs in
    order to tell a double-entry from a deliberate split. Neither changes the
    verdict: the brief asks for records entered twice, and these were.
    """
    values = [entry.value for entry in matches]
    ordered = sorted(matches, key=lambda e: e.entry_id)
    detail = f"System B has {len(matches)} entries for this record"

    if any(value is None for value in values):
        detail += "; at least one has no comparable value."
    elif len({_quantise(value) for value in values}) == 1:
        detail += f"; both report {_quantise(values[0])}."
    else:
        total = sum(values, Decimal("0"))
        if record.value is not None and _quantise(total) == _quantise(record.value):
            # REC-1055: 71950.93 + 107926.39 = 179877.32, labelled "part 2 of 2".
            # Reported anyway. Treating a sum that happens to match as
            # reconciled would invent a splitting rule the brief never defines,
            # and would hide a genuine double-entry that happened to add up.
            detail += f"; their values differ but sum to system A's {_quantise(total)}."
        else:
            detail += f"; their values differ and sum to {_quantise(total)}."

    # The B side of a duplicate has no single value to show. Left empty rather
    # than filled with a sum, which would present a number no system reported.
    return Disagreement(
        reason=DUPLICATE_ENTRY,
        key=record.key,
        record_id=record.record_id,
        org_code=record.org_code,
        location_code=record.location_code,
        a_value=record.value,
        a_value_raw=record.value_raw,
        b_value=None,
        b_value_raw="",
        entry_ids=tuple(entry.entry_id for entry in ordered),
        detail=detail,
        source_lines=tuple(entry.source_line for entry in ordered),
    )


def _compare_pair(record: RecordRow, entry: EntryRow) -> Disagreement | None:
    """Compare one record against its single entry. None when they agree."""
    common = dict(
        key=record.key,
        record_id=record.record_id,
        # The record's org owns the pair. System A is where the record exists,
        # so its location decides whose reconciliation this is.
        org_code=record.org_code,
        location_code=record.location_code,
        a_value=record.value,
        a_value_raw=record.value_raw,
        b_value=entry.value,
        b_value_raw=entry.value_raw,
        entry_ids=(entry.entry_id,),
        source_lines=(record.source_line, entry.source_line),
    )

    if record.value is None or entry.value is None:
        reasons = [
            text for text in (
                _describe_missing(record.value, record.value_raw, "System A"),
                _describe_missing(entry.value, entry.value_raw, "System B"),
            ) if text
        ]
        return Disagreement(
            reason=UNCOMPARABLE,
            detail="; ".join(reasons) + ". The two cannot be compared.",
            **common,
        )

    if _quantise(record.value) != _quantise(entry.value):
        difference = _quantise(record.value) - _quantise(entry.value)
        detail = f"System A reports {_quantise(record.value)}, system B {_quantise(entry.value)}"
        if record.org_code != entry.org_code:
            detail += f"; the entry is also filed at {entry.location_code}, another org's location"
        return Disagreement(reason=VALUE_MISMATCH, detail=detail + ".", **common)

    if record.org_code != entry.org_code and entry.org_code is not None:
        # The values agree, so nothing above catches this -- and yet an entry
        # sitting in one org's location against another org's record is the one
        # thing the brief says must never happen. Silence here would be the
        # worst outcome: a tenancy defect that reconciles cleanly.
        return Disagreement(
            reason=CROSS_ORG_ENTRY,
            detail=(
                f"Values agree, but the entry is filed at {entry.location_code} "
                f"while the record belongs to {record.location_code}. "
                f"The two locations are in different orgs."
            ),
            **common,
        )

    return None


def count_by_reason(found: list[Disagreement]) -> dict[str, int]:
    """Counts per reason, including zeros, in REASONS order.

    Zeros are included so the screen can show every reason it knows about
    rather than only the ones that happen to have occurred.
    """
    counts = {reason: 0 for reason in REASONS}
    for disagreement in found:
        counts[disagreement.reason] += 1
    return counts
