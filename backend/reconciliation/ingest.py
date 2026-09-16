"""
Reading the three CSVs into one batch.

The contract: every data line in every file becomes exactly one row in the
database. A line whose cells cannot be read still becomes a row -- the typed
column is left null, the original text is kept, and a note goes in ImportIssue.
Nothing is skipped, so "rows written == rows read" holds for every file and is
checked before the transaction commits.

Takes open file objects rather than paths, so the management command and the
upload endpoint can share it unchanged. That is the only generality here: the
three files have fixed, known columns and this module assumes them.

The one condition that aborts an import is a location mapped to two different
orgs in the same locations.csv. Everything else is a finding.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import IO, Iterator

from django.db import transaction

from .models import Batch, Entry, ImportIssue, Location, Org, Record
from .parsers import normalize_ref, parse_date, parse_decimal

LOCATIONS_FILE = "locations.csv"
SYSTEM_A_FILE = "system_a.csv"
SYSTEM_B_FILE = "system_b.csv"

LOCATIONS_COLUMNS = ["location_id", "org_id", "location_name"]
SYSTEM_A_COLUMNS = [
    "record_id", "location_id", "event_date", "category_code",
    "actor_id", "base_value", "adjustment", "total_value", "state",
]
SYSTEM_B_COLUMNS = ["entry_id", "record_ref", "location_id", "recorded_on", "value", "label"]

# Cells beyond the header go here rather than being discarded, so a line with
# too many columns is reported instead of silently truncated.
EXTRA_COLUMNS_KEY = "__extra__"


class ImportAborted(Exception):
    """Raised when the data is not merely dirty but self-contradictory.

    Used for exactly one case: a location mapped to two different orgs. That is
    a tenancy boundary contradicting itself, and picking a winner would put one
    org's rows in another org's view.
    """


@dataclass
class FileSummary:
    """What happened to one file. rows_read must equal rows_written."""

    name: str
    rows_read: int = 0
    rows_written: int = 0
    issues: int = 0


@dataclass
class ImportSummary:
    batch_id: int
    label: str
    files: list[FileSummary] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return sum(f.issues for f in self.files)


class _Importer:
    """Holds the batch and the per-file counters while the three files are read.

    A class rather than four functions passing a context dict around: the batch,
    the summary and the location lookup are needed by every step, and threading
    them through by hand made the signatures longer than the bodies.
    """

    def __init__(self, batch: Batch):
        self.batch = batch
        self.summary = ImportSummary(batch_id=batch.id, label=batch.label)
        self.locations: dict[str, Location] = {}
        self.current: FileSummary | None = None

    # ---- issue logging -------------------------------------------------

    def note(self, line: int, field_name: str, raw_value: str, problem: str) -> None:
        """Record one problem. Always paired with keeping the row."""
        ImportIssue.objects.create(
            batch=self.batch,
            source_file=self.current.name,
            line_number=line,
            field=field_name,
            raw_value=(raw_value or "")[:255],
            problem=problem,
        )
        self.current.issues += 1

    # ---- reading -------------------------------------------------------

    def read(self, handle: IO[str], name: str, expected: list[str]) -> Iterator[tuple[int, dict]]:
        """Yield (line_number, row) for each data line, counting as it goes.

        Line numbers are file line numbers, so line 2 is the first data row --
        the coordinate a human gets when they open the CSV and scroll.
        """
        self.current = FileSummary(name=name)
        self.summary.files.append(self.current)

        # No restval, so a line with too few cells leaves those keys as None
        # rather than as empty strings. That is the only way to tell a truncated
        # line apart from one whose cells are genuinely blank, and the two are
        # different problems: the first is a malformed file, the second is data.
        reader = csv.DictReader(handle, restkey=EXTRA_COLUMNS_KEY)
        header = reader.fieldnames or []
        if header != expected:
            # Not fatal: the columns we need may still be present. Reported so a
            # renamed or reordered export is visible rather than mysterious.
            self.note(1, "header", ",".join(header), f"expected columns {','.join(expected)}")

        for line, row in enumerate(reader, start=2):
            self.current.rows_read += 1
            extra = row.pop(EXTRA_COLUMNS_KEY, None)
            if extra:
                self.note(line, "row", ",".join(extra), "more cells than columns; extra cells ignored")
            if any(row.get(column) is None for column in expected):
                missing = [c for c in expected if row.get(c) is None]
                self.note(line, "row", "", f"fewer cells than columns; missing {','.join(missing)}")
            yield line, {column: (row.get(column) or "") for column in expected}

    # ---- the three files -----------------------------------------------

    def load_locations(self, handle: IO[str]) -> None:
        """Read locations.csv first: nothing else can be attributed to an org
        until this mapping exists."""
        orgs: dict[str, Org] = {}

        for line, row in self.read(handle, LOCATIONS_FILE, LOCATIONS_COLUMNS):
            code = row["location_id"].strip()
            org_code = row["org_id"].strip()

            if not code or not org_code:
                self.note(line, "location_id", f"{code}/{org_code}",
                          "location or org code missing; row not used for mapping")
                self.current.rows_written += 1  # counted: read, reported, not mapped
                continue

            existing = self.locations.get(code)
            if existing is not None:
                if existing.org.org_code != org_code:
                    # The one fatal case. See ImportAborted.
                    raise ImportAborted(
                        f"{LOCATIONS_FILE} line {line}: {code} is mapped to both "
                        f"{existing.org.org_code} and {org_code}. The org a row belongs to "
                        f"would be decided by row order, so the import stops here."
                    )
                self.note(line, "location_id", code, "duplicate mapping, identical org; ignored")
                self.current.rows_written += 1
                continue

            org = orgs.get(org_code)
            if org is None:
                org = Org.objects.create(batch=self.batch, org_code=org_code)
                orgs[org_code] = org

            self.locations[code] = Location.objects.create(
                batch=self.batch, org=org, location_code=code,
                location_name=row["location_name"].strip(),
            )
            self.current.rows_written += 1

    def resolve_location(self, line: int, raw: str) -> Location | None:
        """Look up a location code, reporting a miss instead of failing on it.

        A code absent from locations.csv means the row cannot be attributed to
        an org. The row is still stored; it simply will not appear in any org's
        view, which is the safe direction for a tenancy rule to fail in.
        """
        code = raw.strip()
        if not code:
            self.note(line, "location_id", raw, "no location given; row cannot be attributed to an org")
            return None
        location = self.locations.get(code)
        if location is None:
            self.note(line, "location_id", raw,
                      f"{code} is not in {LOCATIONS_FILE}; row cannot be attributed to an org")
        return location

    def money(self, line: int, column: str, raw: str) -> object:
        """Parse a money cell, reporting a failure and returning None.

        A value that needed normalising is noted too, even though it parsed.
        Otherwise the fact that `1,25,400.00` was read correctly is invisible
        outside the raw column, and "the mess was handled" is exactly the thing
        the import log exists to show. A blank cell is not noted: it is an
        absence, and the comparison reports it with more context than this could.
        """
        value, problem = parse_decimal(raw)
        if problem:
            self.note(line, column, raw, f"{problem}; row kept, value left empty")
        elif value is not None and raw.strip() != str(value):
            self.note(line, column, raw, f"read as {value}")
        return value

    def day(self, line: int, column: str, raw: str) -> object:
        value, problem = parse_date(raw)
        if problem:
            self.note(line, column, raw, f"{problem}; row kept, date left empty")
        return value

    def load_records(self, handle: IO[str]) -> None:
        seen: set[str] = set()

        for line, row in self.read(handle, SYSTEM_A_FILE, SYSTEM_A_COLUMNS):
            record_id = row["record_id"].strip()
            if not record_id:
                self.note(line, "record_id", row["record_id"],
                          "no identifier; row stored but nothing can reference it")
            elif record_id in seen:
                # Storable precisely because record_id is not a primary key.
                self.note(line, "record_id", record_id,
                          "appears more than once in this file; both rows kept")
            seen.add(record_id)

            Record.objects.create(
                batch=self.batch,
                record_id=record_id,
                location_code_raw=row["location_id"],
                location=self.resolve_location(line, row["location_id"]),
                event_date=self.day(line, "event_date", row["event_date"]),
                event_date_raw=row["event_date"],
                category_code=row["category_code"].strip(),
                actor_id=row["actor_id"].strip(),
                base_value=self.money(line, "base_value", row["base_value"]),
                base_value_raw=row["base_value"],
                adjustment=self.money(line, "adjustment", row["adjustment"]),
                adjustment_raw=row["adjustment"],
                total_value=self.money(line, "total_value", row["total_value"]),
                total_value_raw=row["total_value"],
                state=row["state"].strip(),
                source_line=line,
            )
            self.current.rows_written += 1

    def load_entries(self, handle: IO[str]) -> None:
        # Records are already in the database, so an entry's reference can be
        # checked as it is read. This is why system_b is loaded last.
        known_refs = {
            normalize_ref(value)
            for value in Record.objects.filter(batch=self.batch).values_list("record_id", flat=True)
        }

        for line, row in self.read(handle, SYSTEM_B_FILE, SYSTEM_B_COLUMNS):
            raw_ref = row["record_ref"]
            normalised = normalize_ref(raw_ref)

            if not normalised:
                self.note(line, "record_ref", raw_ref, "no reference; entry points at nothing")
            elif normalised not in known_refs:
                self.note(line, "record_ref", raw_ref,
                          f"normalised to {normalised}; no such record in {SYSTEM_A_FILE}")
            elif normalised != raw_ref.strip():
                # Not a problem, but worth showing: it is the evidence that the
                # three reference spellings were handled rather than ignored.
                self.note(line, "record_ref", raw_ref, f"normalised to {normalised}; matched")

            Entry.objects.create(
                batch=self.batch,
                entry_id=row["entry_id"].strip(),
                record_ref_raw=raw_ref,
                record_ref_norm=normalised,
                location_code_raw=row["location_id"],
                location=self.resolve_location(line, row["location_id"]),
                recorded_on=self.day(line, "recorded_on", row["recorded_on"]),
                recorded_on_raw=row["recorded_on"],
                value=self.money(line, "value", row["value"]),
                value_raw=row["value"],
                label=row["label"].strip(),
                source_line=line,
            )
            self.current.rows_written += 1


def import_batch(
    label: str,
    locations_file: IO[str],
    system_a_file: IO[str],
    system_b_file: IO[str],
) -> ImportSummary:
    """Load three open CSV files into a new batch and return what happened.

    Everything happens in one transaction: a failure leaves no half-loaded
    batch behind. Raises ImportAborted if locations.csv contradicts itself;
    every other defect is stored and reported.
    """
    with transaction.atomic():
        importer = _Importer(Batch.objects.create(label=label))
        importer.load_locations(locations_file)
        importer.load_records(system_a_file)
        importer.load_entries(system_b_file)

        # The claim this module makes, checked rather than asserted. `assert`
        # would vanish under python -O, and this is the one invariant that
        # proves no row was silently dropped.
        for summary in importer.summary.files:
            if summary.rows_read != summary.rows_written:
                raise ImportAborted(
                    f"{summary.name}: read {summary.rows_read} rows but wrote "
                    f"{summary.rows_written}. Rows were dropped; import rolled back."
                )

        return importer.summary
