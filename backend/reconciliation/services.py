"""
Loading one org's view of one batch.

This is where the tenancy rule lives. `compare.py` compares whatever rows it is
given; everything that decides *which* rows those are happens here, in one
place, so there is a single function to read when someone asks how the boundary
is enforced.

Two rules, and they are the whole of it:

  * A record belongs to the org that owns its location.
  * An entry belongs to the org of the record it references. Only when no such
    record exists does it fall back to the org of its own location.

The second rule is what makes a cross-org entry behave. REC-1077 is ORG-A's
record and its entry is filed at an ORG-B location; the entry is evaluated in
ORG-A's view, where it can be reported as crossing the boundary. Scoping each
side by its own location instead would give ORG-A a record with no entry and
ORG-B an orphan entry -- two findings, both false, and the real defect reported
by neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .compare import (
    CROSS_ORG_ENTRY, DUPLICATE_ENTRY, MISSING_IN_B, ORPHAN_ENTRY, REASONS,
    UNCOMPARABLE, VALUE_MISMATCH, Disagreement, EntryRow, RecordRow,
    compare, count_by_reason,
)
from .models import Batch, Entry, ImportIssue, Org, Record
from .parsers import normalize_ref

# Display text for the screen. Here rather than in compare.py, which holds the
# rules and should not care how they are worded, and not in the frontend, so
# that a reason cannot be renamed in one place and not the other.
REASON_LABELS = {
    MISSING_IN_B: "Missing in system B",
    ORPHAN_ENTRY: "Entry with no record",
    DUPLICATE_ENTRY: "Entered twice",
    VALUE_MISMATCH: "Different values",
    UNCOMPARABLE: "Cannot be compared",
    CROSS_ORG_ENTRY: "Filed against another org",
}

SORT_FIELDS = {"value", "-value"}


class ScopeError(ValueError):
    """A request that does not name exactly one batch and one org.

    Its own type because the view turns it into a 400: there is no sensible
    default for "which tenant", and guessing one is how data leaks.
    """


@dataclass(frozen=True)
class OrgView:
    """One org's disagreements in one batch, plus the counts behind the filter."""

    batch: Batch
    org: Org
    disagreements: list[Disagreement]
    counts: dict[str, int]
    issues: list[ImportIssue]


def _record_rows(batch: Batch) -> list[RecordRow]:
    records = Record.objects.filter(batch=batch).select_related("location__org")
    return [
        RecordRow(
            # Normalised on both sides so that matching compares like with like.
            key=normalize_ref(record.record_id),
            record_id=record.record_id,
            value=record.total_value,
            value_raw=record.total_value_raw,
            location_code=record.location_code_raw,
            org_code=record.location.org.org_code if record.location else None,
            source_line=record.source_line,
            state=record.state,
        )
        for record in records
    ]


def _entry_rows(batch: Batch) -> list[EntryRow]:
    entries = Entry.objects.filter(batch=batch).select_related("location__org")
    return [
        EntryRow(
            entry_id=entry.entry_id,
            key=entry.record_ref_norm,
            record_ref=entry.record_ref_raw,
            value=entry.value,
            value_raw=entry.value_raw,
            location_code=entry.location_code_raw,
            org_code=entry.location.org.org_code if entry.location else None,
            source_line=entry.source_line,
            label=entry.label,
        )
        for entry in entries
    ]


def scope_to_org(
    records: list[RecordRow], entries: list[EntryRow], org_code: str
) -> tuple[list[RecordRow], list[EntryRow]]:
    """Cut the batch down to one org's rows, before any comparison happens.

    Takes the whole batch because an entry's owner is decided by the record it
    references, which may sit in a different org -- that question cannot be
    answered from one org's rows alone. Nothing outside the returned lists ever
    reaches the caller.
    """
    org_of_record = {record.key: record.org_code for record in records}

    scoped_records = [record for record in records if record.org_code == org_code]
    scoped_entries = [
        entry for entry in entries
        # An entry follows its record. Falls back to its own location only when
        # the reference resolves to nothing -- an orphan has no record to
        # inherit an owner from, so it stays with whoever filed it.
        if org_of_record.get(entry.key, entry.org_code) == org_code
    ]
    return scoped_records, scoped_entries


def _issues_for_org(batch: Batch, org_code: str) -> list[ImportIssue]:
    """Import problems this org is allowed to see.

    An issue names a file and a line, so it is attributed by looking up the row
    at that line and following it to an org. Issues that belong to no row --
    a header problem, anything in locations.csv -- are about the import itself
    rather than about one org's data, and are shown to everyone.

    Without this, the health panel would show ORG-A the raw text of ORG-B's
    rows, which is exactly the leak the brief forbids.
    """
    owner: dict[tuple[str, int], str | None] = {}

    for record in Record.objects.filter(batch=batch).select_related("location__org"):
        owner[("system_a.csv", record.source_line)] = (
            record.location.org.org_code if record.location else None
        )

    org_of_record = {
        normalize_ref(record_id): org_code_
        for record_id, org_code_ in Record.objects.filter(batch=batch)
        .select_related("location__org")
        .values_list("record_id", "location__org__org_code")
    }
    for entry in Entry.objects.filter(batch=batch).select_related("location__org"):
        entry_org = entry.location.org.org_code if entry.location else None
        # Same ownership rule as the entries themselves, so an issue about a
        # cross-org entry appears in the same view as the finding it explains.
        owner[("system_b.csv", entry.source_line)] = org_of_record.get(
            entry.record_ref_norm, entry_org
        )

    return [
        issue
        for issue in ImportIssue.objects.filter(batch=batch)
        if owner.get((issue.source_file, issue.line_number), org_code) == org_code
    ]


def load_org_view(batch_id: str | int | None, org_id: str | int | None) -> OrgView:
    """Build one org's view of one batch.

    Both arguments are required. There is deliberately no default batch and no
    "all orgs": the brief's one hard rule is that a row belonging to one tenant
    must never be visible to another, and a default is how that rule gets
    broken by accident.

    Raises ScopeError if either is missing, unknown, or if the org does not
    belong to the batch.
    """
    if batch_id in (None, ""):
        raise ScopeError("a batch must be named")
    if org_id in (None, ""):
        raise ScopeError("an org must be named")

    try:
        batch = Batch.objects.get(pk=batch_id)
    except (Batch.DoesNotExist, ValueError, TypeError):
        raise ScopeError(f"no batch {batch_id!r}") from None

    try:
        # Filtered by batch as well as by id: an org id from another batch must
        # not resolve, or a stale selection in the UI would silently show one
        # batch's org against another batch's rows.
        org = Org.objects.get(pk=org_id, batch=batch)
    except (Org.DoesNotExist, ValueError, TypeError):
        raise ScopeError(f"no org {org_id!r} in batch {batch.pk}") from None

    records, entries = scope_to_org(_record_rows(batch), _entry_rows(batch), org.org_code)
    found = compare(records, entries)

    return OrgView(
        batch=batch,
        org=org,
        disagreements=found,
        # Counted before any reason filter is applied, so the filter can show
        # how many rows each choice would give.
        counts=count_by_reason(found),
        issues=_issues_for_org(batch, org.org_code),
    )


def filter_and_sort(
    found: list[Disagreement], reason: str | None = None, sort: str | None = None
) -> list[Disagreement]:
    """Apply the screen's reason filter and value sort.

    Raises ScopeError on an unknown reason or sort, rather than ignoring it:
    a filter that silently does nothing shows the user more rows than they
    asked for and lets them believe otherwise.
    """
    if reason:
        if reason not in REASONS:
            raise ScopeError(f"unknown reason {reason!r}")
        found = [item for item in found if item.reason == reason]

    if sort:
        if sort not in SORT_FIELDS:
            raise ScopeError(f"unknown sort {sort!r}")
        descending = sort.startswith("-")
        # A finding with no value on either side sorts last in both directions.
        # It has no place on a value axis, and silently treating it as zero
        # would put it among the smallest amounts as though that were known.
        found = sorted(
            found,
            key=lambda item: (
                item.a_value is None and item.b_value is None,
                _sort_value(item, descending),
            ),
        )

    return found


def _sort_value(item: Disagreement, descending: bool) -> Decimal:
    """The amount a finding sorts on: system A's, or system B's when A has none."""
    value = item.a_value if item.a_value is not None else item.b_value
    if value is None:
        return Decimal(0)
    return -value if descending else value
