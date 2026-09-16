"""
Tests for the parsing layer.

Two kinds of test here. The first kind pins the contract: what each function
returns for each shape of bad input. The second kind is the last section --
it opens the actual CSVs and asserts that the dirt in them is exactly the dirt
we think it is. If someone swaps in a file with a new kind of mess, that
section fails rather than the mess passing through unnoticed.

No Django imports and no database: these are plain unittest cases over pure
functions.
"""

import csv
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from reconciliation.parsers import normalize_ref, parse_date, parse_decimal

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class ParseDecimalTests(unittest.TestCase):
    def test_reads_a_plain_value(self):
        self.assertEqual(parse_decimal("88969.92"), (Decimal("88969.92"), None))

    def test_strips_indian_grouping(self):
        # system_b.csv line 63. The whole point of stripping commas rather than
        # assuming three-digit groups.
        value, problem = parse_decimal("1,25,400.00")
        self.assertEqual(value, Decimal("125400.00"))
        self.assertIsNone(problem)

    def test_strips_western_grouping(self):
        self.assertEqual(parse_decimal("125,400.00"), (Decimal("125400.00"), None))

    def test_blank_is_absent_not_a_problem(self):
        # system_b.csv line 50. An empty cell is an absence; reporting it as a
        # parse failure would make the import log cry wolf.
        self.assertEqual(parse_decimal(""), (None, None))
        self.assertEqual(parse_decimal("   "), (None, None))
        self.assertEqual(parse_decimal(None), (None, None))

    def test_unreadable_text_is_a_problem_with_a_reason(self):
        value, problem = parse_decimal("N/A")
        self.assertIsNone(value)
        self.assertIn("not a number", problem)
        self.assertIn("N/A", problem)

    def test_rejects_nan_and_infinity(self):
        # Decimal() accepts both as literals. They would parse silently and then
        # break every comparison they touch, so they are refused here.
        for text in ("NaN", "Infinity", "-inf"):
            with self.subTest(text=text):
                value, problem = parse_decimal(text)
                self.assertIsNone(value, f"{text!r} must not become a value")
                self.assertIsNotNone(problem)

    def test_never_raises(self):
        for text in ("", "-", ".", "1.2.3", "£100", "100-", "--5", "e", "1e99999"):
            with self.subTest(text=text):
                parse_decimal(text)  # a raised exception fails the test

    def test_trailing_zeros_are_preserved_but_compare_equal(self):
        # Decimal keeps the scale it was given, and == ignores it. This is why
        # comparison uses Decimal rather than string equality: 100.50 and
        # 100.500 are the same amount written two ways, not a disagreement.
        a, _ = parse_decimal("100.50")
        b, _ = parse_decimal("100.500")
        self.assertNotEqual(str(a), str(b))
        self.assertEqual(a, b)


class ParseDateTests(unittest.TestCase):
    def test_reads_an_iso_date(self):
        self.assertEqual(parse_date("2026-04-03"), (date(2026, 4, 3), None))

    def test_tolerates_surrounding_whitespace(self):
        self.assertEqual(parse_date("  2026-04-03 "), (date(2026, 4, 3), None))

    def test_blank_is_absent_not_a_problem(self):
        self.assertEqual(parse_date(""), (None, None))
        self.assertEqual(parse_date(None), (None, None))

    def test_ambiguous_format_is_refused_rather_than_guessed(self):
        # 03/04/2026 is either 3 April or 4 March. Picking one would invent a
        # fact, so it is reported instead.
        value, problem = parse_date("03/04/2026")
        self.assertIsNone(value)
        self.assertIn("not an ISO date", problem)

    def test_impossible_day_is_refused(self):
        # Matches the ISO pattern but is not a day that exists.
        value, problem = parse_date("2026-02-30")
        self.assertIsNone(value)
        self.assertIn("not a real date", problem)

    def test_never_raises(self):
        for text in ("", "2026", "2026-13-01", "2026-00-10", "yesterday", "0000-00-00"):
            with self.subTest(text=text):
                parse_date(text)


class NormalizeRefTests(unittest.TestCase):
    def test_the_three_spellings_in_the_file_reach_the_same_key(self):
        # The brief promises references written three different ways. These are
        # the three, taken from system_b.csv lines 34, 69 and 111. If any one of
        # them fails to normalise, the comparison reports a false orphan and a
        # false missing-entry for a record that was matched correctly by the
        # other two.
        self.assertEqual(normalize_ref("rec1034"), "REC-1034")
        self.assertEqual(normalize_ref(" REC - 1070 "), "REC-1070")
        self.assertEqual(normalize_ref("1112"), "REC-1112")

    def test_already_clean_references_are_unchanged(self):
        self.assertEqual(normalize_ref("REC-1001"), "REC-1001")

    def test_casing_and_whitespace_are_not_disagreements(self):
        variants = ["REC-1001", "rec-1001", "  REC-1001  ", "Rec 1001", "rec_1001", "REC1001"]
        self.assertEqual({normalize_ref(v) for v in variants}, {"REC-1001"})

    def test_empty_reference_matches_nothing(self):
        # Empty must not normalise to something that matches a record.
        self.assertEqual(normalize_ref(""), "")
        self.assertEqual(normalize_ref("   "), "")
        self.assertEqual(normalize_ref(None), "")
        self.assertEqual(normalize_ref("-/-"), "")

    def test_near_misses_are_left_alone(self):
        # REC-1999 does not exist in system_a.csv. It is close to REC-1099 and
        # to REC-1009, and it is neither. Normalisation fixes how a reference is
        # written, never what it says.
        self.assertEqual(normalize_ref("REC-1999"), "REC-1999")
        self.assertNotEqual(normalize_ref("REC-1999"), normalize_ref("REC-1099"))

    def test_unexpected_shape_survives_instead_of_vanishing(self):
        # Not a shape we expect, but it must still come back as something that
        # can be displayed and reported.
        self.assertEqual(normalize_ref("1034-REC"), "1034REC")


class RealFileTests(unittest.TestCase):
    """The dirt in the actual files is the specification.

    These read backend/data/*.csv and assert what is wrong with them. They are
    here so that a change in the source data is caught by a failing test rather
    than discovered on screen.
    """

    def rows(self, filename):
        with open(DATA_DIR / filename, newline="", encoding="utf-8") as handle:
            yield from enumerate(csv.DictReader(handle), start=2)

    def test_every_system_a_value_and_date_reads_cleanly(self):
        for line, row in self.rows("system_a.csv"):
            for column in ("base_value", "adjustment", "total_value"):
                value, problem = parse_decimal(row[column])
                self.assertIsNone(problem, f"line {line} {column}: {problem}")
                self.assertIsNotNone(value, f"line {line} {column} unexpectedly blank")
            event_date, problem = parse_date(row["event_date"])
            self.assertIsNone(problem, f"line {line} event_date: {problem}")
            self.assertIsNotNone(event_date)

    def test_system_b_has_exactly_one_blank_value_and_one_grouped_value(self):
        blank, grouped, failed = [], [], []
        for line, row in self.rows("system_b.csv"):
            raw = row["value"]
            value, problem = parse_decimal(raw)
            if problem:
                failed.append((line, raw, problem))
            elif value is None:
                blank.append(line)
            elif raw.strip() != str(value):
                grouped.append((line, raw, value))

        self.assertEqual(failed, [], "no value in system_b.csv should be unreadable")
        self.assertEqual(blank, [50], "the blank value is line 50")
        self.assertEqual(grouped, [(63, "1,25,400.00", Decimal("125400.00"))])

    def test_every_system_b_date_reads_cleanly(self):
        for line, row in self.rows("system_b.csv"):
            value, problem = parse_date(row["recorded_on"])
            self.assertIsNone(problem, f"line {line} recorded_on: {problem}")
            self.assertIsNotNone(value)

    def test_every_reference_normalises_and_three_needed_it(self):
        untidy = []
        for line, row in self.rows("system_b.csv"):
            raw = row["record_ref"]
            normalised = normalize_ref(raw)
            self.assertNotEqual(normalised, "", f"line {line}: reference normalised to nothing")
            if raw != normalised:
                untidy.append((line, raw, normalised))

        self.assertEqual(
            untidy,
            [(34, "rec1034", "REC-1034"),
             (69, " REC - 1070 ", "REC-1070"),
             (111, "1112", "REC-1112")],
        )

    def test_normalisation_does_not_collide_two_records_into_one(self):
        # Normalising too aggressively would merge distinct identifiers and hide
        # a real disagreement. Every record_id in system_a must still be unique
        # after normalisation.
        keys = [normalize_ref(row["record_id"]) for _, row in self.rows("system_a.csv")]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_system_b_reference_that_looks_resolvable_finds_a_record(self):
        # The one exception is the orphan the brief promises. Naming it here
        # means a second orphan appearing later fails this test.
        records = {normalize_ref(row["record_id"]) for _, row in self.rows("system_a.csv")}
        unmatched = sorted(
            {normalize_ref(row["record_ref"]) for _, row in self.rows("system_b.csv")} - records
        )
        self.assertEqual(unmatched, ["REC-1999"])
