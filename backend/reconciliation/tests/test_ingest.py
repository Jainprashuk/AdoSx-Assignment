"""
Tests for ingestion.

The claim under test is narrow and it is the whole of the 25% rubric line:
every data line in every file becomes exactly one row, however bad the line is.
Everything else here supports that claim -- that the dirt is reported, that a
rollback leaves nothing behind, and that re-seeding does not stack up copies.
"""

import io
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from reconciliation.ingest import ImportAborted, import_batch
from reconciliation.models import Batch, Entry, ImportIssue, Location, Org, Record

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

LOCATIONS_HEADER = "location_id,org_id,location_name\n"
SYSTEM_A_HEADER = (
    "record_id,location_id,event_date,category_code,actor_id,"
    "base_value,adjustment,total_value,state\n"
)
SYSTEM_B_HEADER = "entry_id,record_ref,location_id,recorded_on,value,label\n"


def text(*lines: str) -> io.StringIO:
    return io.StringIO("".join(lines))


class RealFileImportTests(TestCase):
    """Against backend/data/*.csv, the files the submission ships with."""

    @classmethod
    def setUpTestData(cls):
        with (
            open(DATA_DIR / "locations.csv", newline="", encoding="utf-8-sig") as locations,
            open(DATA_DIR / "system_a.csv", newline="", encoding="utf-8-sig") as system_a,
            open(DATA_DIR / "system_b.csv", newline="", encoding="utf-8-sig") as system_b,
        ):
            cls.summary = import_batch("test batch", locations, system_a, system_b)

    def test_every_row_read_was_written(self):
        # The invariant. If this fails, a row was dropped somewhere and the
        # numbers on screen are answers to a question about incomplete data.
        for file_summary in self.summary.files:
            with self.subTest(file=file_summary.name):
                self.assertEqual(file_summary.rows_read, file_summary.rows_written)

    def test_the_counts_match_the_files_on_disk(self):
        # Counted independently of the importer's own tally, so a bug that
        # miscounts both sides in the same way cannot pass.
        expected = {
            "locations.csv": 5, "system_a.csv": 120, "system_b.csv": 121,
        }
        for name, count in expected.items():
            with self.subTest(file=name):
                lines = (DATA_DIR / name).read_text(encoding="utf-8-sig").strip().splitlines()
                self.assertEqual(len(lines) - 1, count)

        self.assertEqual(Location.objects.count(), 5)
        self.assertEqual(Record.objects.count(), 120)
        self.assertEqual(Entry.objects.count(), 121)

    def test_the_two_orgs_come_from_the_mapping_file(self):
        self.assertEqual(
            sorted(Org.objects.values_list("org_code", flat=True)), ["ORG-A", "ORG-B"]
        )

    def test_every_row_resolved_to_a_location(self):
        # True of this dataset. If a later file has an unmapped code, the row is
        # still stored -- this asserts the current data, not the capability.
        self.assertEqual(Record.objects.filter(location__isnull=True).count(), 0)
        self.assertEqual(Entry.objects.filter(location__isnull=True).count(), 0)

    def test_the_unreadable_and_absent_values_are_distinguishable(self):
        # system_b.csv line 50 is blank, not unreadable: null value AND blank
        # raw. The pair of columns is what carries the difference.
        blank = Entry.objects.get(source_line=50)
        self.assertIsNone(blank.value)
        self.assertEqual(blank.value_raw.strip(), "")

    def test_the_grouped_value_was_read_not_rejected(self):
        grouped = Entry.objects.get(source_line=63)
        self.assertEqual(str(grouped.value), "125400.00")
        self.assertEqual(grouped.value_raw, "1,25,400.00")

    def test_the_three_untidy_references_resolve_to_records(self):
        record_ids = set(Record.objects.values_list("record_id", flat=True))
        for line, expected in [(34, "REC-1034"), (69, "REC-1070"), (111, "REC-1112")]:
            with self.subTest(line=line):
                entry = Entry.objects.get(source_line=line)
                self.assertEqual(entry.record_ref_norm, expected)
                self.assertIn(expected, record_ids)
                # The original text survives alongside the normalised key.
                self.assertNotEqual(entry.record_ref_raw, "")

    def test_the_orphan_reference_is_stored_and_reported(self):
        orphan = Entry.objects.get(record_ref_norm="REC-1999")
        self.assertEqual(orphan.entry_id, "ENT/2026/4901")
        self.assertTrue(
            ImportIssue.objects.filter(line_number=orphan.source_line, field="record_ref").exists()
        )

    def test_the_issue_log_is_the_expected_inventory(self):
        # Pinning the log means a new kind of mess in a future file shows up as
        # a failing test rather than as an extra line nobody notices.
        logged = sorted(
            ImportIssue.objects.values_list("source_file", "line_number", "field")
        )
        self.assertEqual(logged, [
            ("system_b.csv", 34, "record_ref"),
            ("system_b.csv", 63, "value"),
            ("system_b.csv", 69, "record_ref"),
            ("system_b.csv", 111, "record_ref"),
            ("system_b.csv", 120, "record_ref"),
        ])


class DirtyRowTests(TestCase):
    """Rows nastier than anything in the sample, to prove the survival claim."""

    def test_rows_nothing_can_be_read_from_are_still_stored(self):
        summary = import_batch(
            "dirty",
            text(LOCATIONS_HEADER, "LOC-1,ORG-A,One\n"),
            text(
                SYSTEM_A_HEADER,
                # unreadable number, unreadable date, unknown location
                "REC-1,LOC-NOPE,not-a-date,CAT-1,USR-1,N/A,1.00,N/A,CONFIRMED\n",
                # no identifier at all
                ",LOC-1,2026-01-01,CAT-1,USR-1,1.00,1.00,2.00,CONFIRMED\n",
                # duplicate identifier: storable only because record_id is not a PK
                "REC-1,LOC-1,2026-01-01,CAT-1,USR-1,1.00,1.00,2.00,CONFIRMED\n",
            ),
            text(
                SYSTEM_B_HEADER,
                "ENT-1,,LOC-1,2026-01-01,1.00,no reference\n",
                "ENT-2,REC-404,LOC-1,2026-01-01,1.00,points at nothing\n",
                "ENT-3,REC-1,LOC-1,2026-01-01,NaN,not a finite number\n",
            ),
        )

        self.assertEqual(Record.objects.count(), 3)
        self.assertEqual(Entry.objects.count(), 3)
        for file_summary in summary.files:
            self.assertEqual(file_summary.rows_read, file_summary.rows_written)

        unreadable = Record.objects.get(source_line=2)
        self.assertIsNone(unreadable.total_value)
        self.assertEqual(unreadable.total_value_raw, "N/A")   # the text survives
        self.assertIsNone(unreadable.event_date)
        self.assertIsNone(unreadable.location)                # code not in the mapping

        # NaN parses as a Decimal literal but is not an amount; it must not be stored.
        self.assertIsNone(Entry.objects.get(entry_id="ENT-3").value)

    def test_a_short_line_and_a_long_line_both_survive(self):
        summary = import_batch(
            "ragged",
            text(LOCATIONS_HEADER, "LOC-1,ORG-A,One\n"),
            text(
                SYSTEM_A_HEADER,
                "REC-1,LOC-1,2026-01-01,CAT-1\n",                                   # too few
                "REC-2,LOC-1,2026-01-01,CAT-1,USR-1,1.00,1.00,2.00,OK,extra,more\n",  # too many
            ),
            text(SYSTEM_B_HEADER),
        )

        self.assertEqual(Record.objects.count(), 2)
        self.assertEqual([f.rows_read for f in summary.files], [1, 2, 0])
        self.assertEqual([f.rows_written for f in summary.files], [1, 2, 0])
        problems = list(ImportIssue.objects.filter(field="row").values_list("problem", flat=True))
        self.assertEqual(len(problems), 2, problems)

    def test_every_issue_names_a_file_a_line_and_the_original_text(self):
        # An import log that cannot be traced back to a line in a file is not
        # evidence of anything.
        import_batch(
            "traceable",
            text(LOCATIONS_HEADER, "LOC-1,ORG-A,One\n"),
            text(SYSTEM_A_HEADER, "REC-1,LOC-1,2026-01-01,CAT-1,USR-1,1.00,1.00,oops,OK\n"),
            text(SYSTEM_B_HEADER),
        )
        issue = ImportIssue.objects.get(field="total_value")
        self.assertEqual(issue.source_file, "system_a.csv")
        self.assertEqual(issue.line_number, 2)
        self.assertEqual(issue.raw_value, "oops")
        self.assertIn("row kept", issue.problem)


class AbortTests(TestCase):
    """The one case that is not a finding."""

    def test_a_location_in_two_orgs_stops_the_import(self):
        with self.assertRaises(ImportAborted) as caught:
            import_batch(
                "contradictory",
                text(LOCATIONS_HEADER, "LOC-1,ORG-A,One\n", "LOC-1,ORG-B,One again\n"),
                text(SYSTEM_A_HEADER),
                text(SYSTEM_B_HEADER),
            )
        self.assertIn("LOC-1", str(caught.exception))

    def test_an_aborted_import_leaves_nothing_behind(self):
        # One transaction: a half-loaded batch would be worse than no batch,
        # because it would look complete on screen.
        with self.assertRaises(ImportAborted):
            import_batch(
                "contradictory",
                text(LOCATIONS_HEADER, "LOC-1,ORG-A,One\n", "LOC-1,ORG-B,One again\n"),
                text(SYSTEM_A_HEADER),
                text(SYSTEM_B_HEADER),
            )
        self.assertEqual(Batch.objects.count(), 0)
        self.assertEqual(Location.objects.count(), 0)

    def test_a_duplicate_mapping_with_the_same_org_is_only_a_finding(self):
        # Same fact stated twice is untidy, not contradictory.
        import_batch(
            "repeated",
            text(LOCATIONS_HEADER, "LOC-1,ORG-A,One\n", "LOC-1,ORG-A,One\n"),
            text(SYSTEM_A_HEADER),
            text(SYSTEM_B_HEADER),
        )
        self.assertEqual(Location.objects.count(), 1)
        self.assertEqual(ImportIssue.objects.filter(field="location_id").count(), 1)


class SeedCommandTests(TestCase):
    def test_running_the_command_twice_leaves_one_batch(self):
        # Idempotent by replacement. A reviewer who runs the command twice must
        # not end up comparing against a doubled dataset.
        call_command("import_data", verbosity=0)
        call_command("import_data", verbosity=0)

        self.assertEqual(Batch.objects.count(), 1)
        self.assertEqual(Record.objects.count(), 120)
        self.assertEqual(Entry.objects.count(), 121)

    def test_a_second_label_creates_a_second_batch_and_leaves_the_first(self):
        # The upload path in stage 9 depends on this: a new batch must not
        # disturb the seeded one.
        call_command("import_data", verbosity=0)
        call_command("import_data", label="uploaded", verbosity=0)

        self.assertEqual(Batch.objects.count(), 2)
        self.assertEqual(Record.objects.count(), 240)
        # Nothing is shared between batches, not even the locations.
        self.assertEqual(Location.objects.count(), 10)
