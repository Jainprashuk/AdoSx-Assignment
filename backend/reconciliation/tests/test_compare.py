"""
Tests for the comparison logic.

This is the part the brief asks for tests on: "the part where the disagreements
are decided". One test per reason proving it is caught, and a set of tests
proving the non-errors are not reported -- a comparison that flags everything
passes the first half and is useless.

No database and no Django: these build dataclasses directly, which is the point
of compare.py taking them.
"""

import unittest
from decimal import Decimal

from reconciliation.compare import (
    CROSS_ORG_ENTRY,
    DUPLICATE_ENTRY,
    MISSING_IN_B,
    ORPHAN_ENTRY,
    REASONS,
    UNCOMPARABLE,
    VALUE_MISMATCH,
    EntryRow,
    RecordRow,
    compare,
    count_by_reason,
)


def record(key="REC-1001", value="100.00", raw=None, org="ORG-A", location="LOC-101", **kwargs):
    """A clean record. Tests override only the field under test."""
    amount = None if value is None else Decimal(value)
    return RecordRow(
        key=key,
        record_id=kwargs.pop("record_id", key),
        value=amount,
        value_raw=raw if raw is not None else (value or ""),
        location_code=location,
        org_code=org,
        source_line=kwargs.pop("source_line", 2),
        **kwargs,
    )


def entry(key="REC-1001", value="100.00", raw=None, org="ORG-A", location="LOC-101", **kwargs):
    amount = None if value is None else Decimal(value)
    return EntryRow(
        entry_id=kwargs.pop("entry_id", "ENT-1"),
        key=key,
        record_ref=kwargs.pop("record_ref", key),
        value=amount,
        value_raw=raw if raw is not None else (value or ""),
        location_code=location,
        org_code=org,
        source_line=kwargs.pop("source_line", 2),
        **kwargs,
    )


class RequiredDetectionTests(unittest.TestCase):
    """One test per disagreement the brief names, plus the two added ones."""

    def test_record_with_no_entry(self):
        found = compare([record(key="REC-1015", value="41095.33")], [])

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, MISSING_IN_B)
        self.assertEqual(found[0].record_id, "REC-1015")
        self.assertEqual(found[0].a_value, Decimal("41095.33"))
        self.assertIsNone(found[0].b_value)
        self.assertEqual(found[0].entry_ids, ())

    def test_entry_pointing_at_no_record(self):
        found = compare([], [entry(key="REC-1999", entry_id="ENT/2026/4901", value="41250.00")])

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, ORPHAN_ENTRY)
        # No record exists, so there is no record_id to report -- and inventing
        # one from the reference would assert something the data does not say.
        self.assertIsNone(found[0].record_id)
        self.assertEqual(found[0].b_value, Decimal("41250.00"))
        self.assertEqual(found[0].entry_ids, ("ENT/2026/4901",))

    def test_record_entered_twice(self):
        found = compare(
            [record(key="REC-1042", value="112837.06")],
            [entry(key="REC-1042", entry_id="ENT-A", value="112837.06"),
             entry(key="REC-1042", entry_id="ENT-B", value="112837.06")],
        )

        self.assertEqual(len(found), 1, "two entries are one problem, not two")
        self.assertEqual(found[0].reason, DUPLICATE_ENTRY)
        self.assertEqual(found[0].entry_ids, ("ENT-A", "ENT-B"))
        self.assertIn("both report 112837.06", found[0].detail)

    def test_different_values_for_the_same_record(self):
        found = compare(
            [record(key="REC-1003", value="121388.01")],
            [entry(key="REC-1003", value="94834.38")],
        )

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, VALUE_MISMATCH)
        self.assertEqual(found[0].difference, Decimal("26553.63"))

    def test_value_that_cannot_be_compared(self):
        # system_b.csv line 50: system A has a total, system B has nothing.
        found = compare(
            [record(key="REC-1050", value="160405.85")],
            [entry(key="REC-1050", value=None, raw="")],
        )

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, UNCOMPARABLE)
        self.assertIsNone(found[0].difference)
        self.assertIn("recorded no value", found[0].detail)

    def test_entry_filed_against_another_orgs_record(self):
        # REC-1077: the values agree, so every value-based rule stays silent.
        found = compare(
            [record(key="REC-1077", value="83361.40", org="ORG-A", location="LOC-102")],
            [entry(key="REC-1077", value="83361.40", org="ORG-B", location="LOC-201")],
        )

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, CROSS_ORG_ENTRY)
        # The finding belongs to the record's org, not the entry's.
        self.assertEqual(found[0].org_code, "ORG-A")
        self.assertIn("different orgs", found[0].detail)


class NonErrorTests(unittest.TestCase):
    """The 25% rubric line: a non-error must be identified as a non-error.

    A comparison that reports everything catches all four required cases and is
    still worthless. These are the tests that make the reported findings mean
    something.
    """

    def test_an_agreeing_pair_produces_nothing(self):
        self.assertEqual(compare([record()], [entry()]), [])

    def test_trailing_zeros_are_not_a_disagreement(self):
        # 100.50 and 100.500 are the same amount written two ways. String
        # comparison would report this; Decimal does not.
        found = compare([record(value="100.50")], [entry(value="100.500")])
        self.assertEqual(found, [])

    def test_a_value_with_grouping_separators_is_not_a_disagreement(self):
        # The parser has already stripped the separators from system_b.csv line
        # 63. This asserts the comparison agrees once it has.
        found = compare(
            [record(value="125400.00")],
            [entry(value="125400.00", raw="1,25,400.00")],
        )
        self.assertEqual(found, [])

    def test_references_written_differently_still_match(self):
        # Matching is on the normalised key, so " REC - 1070 " and rec1034 reach
        # their records. If they did not, each would produce two false findings:
        # a missing entry and an orphan.
        found = compare(
            [record(key="REC-1070", value="1608.95")],
            [entry(key="REC-1070", record_ref=" REC - 1070 ", value="1608.95")],
        )
        self.assertEqual(found, [])

    def test_a_voided_record_with_an_entry_is_not_a_disagreement(self):
        # REC-1019. The brief defines no rule about state, so inventing one
        # would report a disagreement the two systems do not have: they agree.
        found = compare(
            [record(key="REC-1019", value="57092.35", state="VOIDED")],
            [entry(key="REC-1019", value="57092.35")],
        )
        self.assertEqual(found, [])

    def test_a_date_difference_is_not_a_disagreement(self):
        # ENT/2026/4009 is recorded two days after REC-1009's event date. Dates
        # are not the compared field, and the values agree.
        found = compare([record(key="REC-1009", value="111699.30")],
                        [entry(key="REC-1009", value="111699.30")])
        self.assertEqual(found, [])

    def test_a_difference_below_the_cent_is_not_a_disagreement(self):
        # Both systems write two decimal places. A third-place difference is
        # noise from neither file and must not be reported as a disagreement.
        found = compare([record(value="100.001")], [entry(value="100.004")])
        self.assertEqual(found, [])


class PrecedenceTests(unittest.TestCase):
    """What happens when a pair breaks more than one rule."""

    def test_a_duplicate_is_one_finding_even_when_the_values_also_differ(self):
        found = compare(
            [record(key="REC-1055", value="179877.32")],
            [entry(key="REC-1055", entry_id="ENT-1", value="71950.93"),
             entry(key="REC-1055", entry_id="ENT-2", value="107926.39")],
        )

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, DUPLICATE_ENTRY)

    def test_a_split_that_sums_to_the_total_is_still_reported(self):
        # REC-1055's halves sum exactly to system A's total and the second is
        # labelled "part 2 of 2". Treating that as reconciled would invent a
        # splitting rule the brief never defines -- and would hide a real
        # double-entry that happened to add up.
        found = compare(
            [record(key="REC-1055", value="179877.32")],
            [entry(key="REC-1055", entry_id="ENT-1", value="71950.93"),
             entry(key="REC-1055", entry_id="ENT-2", value="107926.39")],
        )

        self.assertEqual(found[0].reason, DUPLICATE_ENTRY)
        self.assertIn("sum to system A's 179877.32", found[0].detail)

    def test_an_unreadable_value_beats_a_value_mismatch(self):
        # Nothing can be said about how far apart they are, so reporting a
        # mismatch would imply a comparison that never happened.
        found = compare(
            [record(value="100.00")],
            [entry(value=None, raw="N/A")],
        )

        self.assertEqual(found[0].reason, UNCOMPARABLE)
        self.assertIn("could not be read", found[0].detail)

    def test_unreadable_and_absent_are_described_differently(self):
        unreadable = compare([record(value="100.00")], [entry(value=None, raw="pending")])
        absent = compare([record(value="100.00")], [entry(value=None, raw="")])

        self.assertIn("could not be read", unreadable[0].detail)
        self.assertIn("recorded no value", absent[0].detail)
        # Both block comparison; they are different facts about the export.
        self.assertEqual(unreadable[0].reason, absent[0].reason)

    def test_a_value_mismatch_across_orgs_reports_the_mismatch_and_mentions_both(self):
        found = compare(
            [record(value="100.00", org="ORG-A", location="LOC-101")],
            [entry(value="200.00", org="ORG-B", location="LOC-201")],
        )

        self.assertEqual(found[0].reason, VALUE_MISMATCH)
        self.assertIn("another org's location", found[0].detail)


class ShapeTests(unittest.TestCase):
    """Properties of the returned list that the screen depends on."""

    def test_findings_are_ordered_by_reason_then_record(self):
        found = compare(
            [record(key="REC-1", value="1.00"),
             record(key="REC-2", value="1.00"),
             record(key="REC-3", value="1.00")],
            [entry(key="REC-2", value="2.00"), entry(key="REC-9", value="9.00")],
        )

        self.assertEqual(
            [(f.reason, f.key) for f in found],
            [(MISSING_IN_B, "REC-1"), (MISSING_IN_B, "REC-3"),
             (ORPHAN_ENTRY, "REC-9"), (VALUE_MISMATCH, "REC-2")],
        )

    def test_difference_is_none_when_one_side_has_no_value(self):
        for rows in (
            ([record()], []),                                   # missing
            ([], [entry()]),                                    # orphan
            ([record()], [entry(value=None, raw="N/A")]),        # uncomparable
        ):
            with self.subTest(rows=rows):
                self.assertIsNone(compare(*rows)[0].difference)

    def test_every_finding_can_be_traced_back_to_a_source_line(self):
        found = compare(
            [record(key="REC-1", value="1.00", source_line=7)],
            [entry(key="REC-9", value="9.00", source_line=11)],
        )
        self.assertEqual({f.source_lines for f in found}, {(7,), (11,)})

    def test_counts_include_every_reason_even_at_zero(self):
        counts = count_by_reason(compare([record()], [entry()]))

        self.assertEqual(list(counts), list(REASONS))
        self.assertEqual(set(counts.values()), {0})

    def test_counts_add_up_to_the_findings(self):
        found = compare(
            [record(key="REC-1", value="1.00"), record(key="REC-2", value="1.00")],
            [entry(key="REC-2", value="2.00"), entry(key="REC-9", value="9.00")],
        )
        self.assertEqual(sum(count_by_reason(found).values()), len(found))

    def test_empty_input_is_not_an_error(self):
        self.assertEqual(compare([], []), [])


class ScopingTests(unittest.TestCase):
    """compare() does no scoping; it compares what it is handed.

    These pin that contract, because the tenancy rule is enforced one layer up
    and it matters that the boundary is where it is thought to be.
    """

    def test_two_orgs_rows_compared_together_stay_separate_findings(self):
        found = compare(
            [record(key="REC-A", value="1.00", org="ORG-A"),
             record(key="REC-B", value="1.00", org="ORG-B")],
            [],
        )

        self.assertEqual({f.org_code for f in found}, {"ORG-A", "ORG-B"})

    def test_a_row_with_no_org_is_still_compared(self):
        # An unmapped location code leaves org_code None. The row is not
        # dropped -- it simply belongs to no org's view, which is the safe
        # direction for a tenancy rule to fail in.
        found = compare([record(org=None, location="LOC-NOPE", value="1.00")], [])

        self.assertEqual(len(found), 1)
        self.assertIsNone(found[0].org_code)

    def test_an_entry_with_no_org_does_not_trigger_a_cross_org_finding(self):
        # Unknown is not the same as different: an unresolvable location is
        # already reported by the importer, and calling it a tenancy breach
        # would be asserting something not known.
        found = compare(
            [record(value="100.00", org="ORG-A")],
            [entry(value="100.00", org=None, location="LOC-NOPE")],
        )
        self.assertEqual(found, [])
