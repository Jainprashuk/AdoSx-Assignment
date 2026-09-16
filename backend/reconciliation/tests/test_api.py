"""
Tests for scoping and the endpoints.

The brief states the tenancy rule in prose rather than in the task list, which
makes it the easiest requirement to satisfy loosely and never notice. These are
the tests that make it a rule rather than an intention: a request that names no
org is refused, and one org's view contains nothing of another's.
"""

import json

from django.core.management import call_command
from django.test import TestCase

from reconciliation.compare import CROSS_ORG_ENTRY, MISSING_IN_B, ORPHAN_ENTRY
from reconciliation.models import Batch, Org
from reconciliation.services import ScopeError, load_org_view


class ScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_data", verbosity=0)
        cls.batch = Batch.objects.get()
        cls.org_a = Org.objects.get(batch=cls.batch, org_code="ORG-A")
        cls.org_b = Org.objects.get(batch=cls.batch, org_code="ORG-B")

    def test_a_request_without_an_org_is_rejected(self):
        # The one rule the brief states in prose rather than in the task list.
        # There is no sensible default for "which tenant", and a default is how
        # the boundary gets crossed by accident.
        with self.assertRaises(ScopeError):
            load_org_view(self.batch.pk, None)

    def test_a_request_without_a_batch_is_rejected(self):
        with self.assertRaises(ScopeError):
            load_org_view(None, self.org_a.pk)

    def test_an_org_from_another_batch_does_not_resolve(self):
        # A stale org id left in the UI after switching batches must not quietly
        # show one batch's org against another batch's rows.
        call_command("import_data", label="second", verbosity=0)
        other = Batch.objects.exclude(pk=self.batch.pk).get()

        with self.assertRaises(ScopeError):
            load_org_view(other.pk, self.org_a.pk)

    def test_each_org_sees_only_its_own_findings(self):
        a = load_org_view(self.batch.pk, self.org_a.pk)
        b = load_org_view(self.batch.pk, self.org_b.pk)

        self.assertEqual({d.org_code for d in a.disagreements}, {"ORG-A"})
        self.assertEqual({d.org_code for d in b.disagreements}, {"ORG-B"})
        self.assertEqual(len(a.disagreements), 8)
        self.assertEqual(len(b.disagreements), 3)

    def test_no_record_appears_in_both_orgs(self):
        a = load_org_view(self.batch.pk, self.org_a.pk)
        b = load_org_view(self.batch.pk, self.org_b.pk)

        self.assertEqual({d.key for d in a.disagreements} & {d.key for d in b.disagreements}, set())

    def test_the_two_views_together_are_the_whole_batch(self):
        # Scoping must partition the findings, not sample them. If the two
        # views summed to fewer than the total, a disagreement would exist that
        # nobody is shown.
        a = load_org_view(self.batch.pk, self.org_a.pk)
        b = load_org_view(self.batch.pk, self.org_b.pk)

        self.assertEqual(len(a.disagreements) + len(b.disagreements), 11)

    def test_the_cross_org_entry_is_reported_to_the_records_org_only(self):
        # REC-1077: ORG-A's record, entry filed at an ORG-B location.
        a = load_org_view(self.batch.pk, self.org_a.pk)
        b = load_org_view(self.batch.pk, self.org_b.pk)

        cross = [d for d in a.disagreements if d.reason == CROSS_ORG_ENTRY]
        self.assertEqual([d.key for d in cross], ["REC-1077"])

        # And ORG-B must not see it as an orphan entry, which is what naive
        # per-location scoping would produce.
        self.assertEqual(
            [d.key for d in b.disagreements if d.reason == ORPHAN_ENTRY], []
        )
        self.assertNotIn("REC-1077", {d.key for d in b.disagreements})

    def test_scoping_does_not_invent_a_missing_entry(self):
        # The other half of the same trap: ORG-A must see REC-1077 as a
        # cross-org finding, never as a record with no entry.
        a = load_org_view(self.batch.pk, self.org_a.pk)
        missing = [d.key for d in a.disagreements if d.reason == MISSING_IN_B]

        self.assertNotIn("REC-1077", missing)
        self.assertEqual(missing, ["REC-1015"])

    def test_import_issues_are_scoped_too(self):
        # The health panel shows raw text from the source rows. Unscoped, it
        # would show one org the contents of another org's lines.
        a = load_org_view(self.batch.pk, self.org_a.pk)
        b = load_org_view(self.batch.pk, self.org_b.pk)

        a_lines = {(i.source_file, i.line_number) for i in a.issues}
        b_lines = {(i.source_file, i.line_number) for i in b.issues}
        self.assertEqual(a_lines & b_lines, set())
        self.assertEqual(len(a.issues) + len(b.issues), 5)


class EndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_data", verbosity=0)
        cls.batch = Batch.objects.get()
        cls.org_a = Org.objects.get(batch=cls.batch, org_code="ORG-A")

    def get(self, path, **params):
        response = self.client.get(path, params)
        return response, json.loads(response.content)

    def test_discrepancies_without_an_org_is_a_400(self):
        response, body = self.get("/api/discrepancies/", batch=self.batch.pk)

        self.assertEqual(response.status_code, 400)
        self.assertIn("org", body["error"])

    def test_discrepancies_without_a_batch_is_a_400(self):
        response, _ = self.get("/api/discrepancies/", org=self.org_a.pk)
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_org_is_a_400_not_an_empty_list(self):
        # An empty list would read as "this org has no disagreements", which is
        # a different and much more comforting statement than "no such org".
        response, _ = self.get("/api/discrepancies/", batch=self.batch.pk, org=9999)
        self.assertEqual(response.status_code, 400)

    def test_a_scoped_request_returns_that_orgs_rows(self):
        response, body = self.get(
            "/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["org"]["code"], "ORG-A")
        self.assertEqual(body["total"], 8)
        self.assertEqual(len(body["disagreements"]), 8)

    def test_money_crosses_the_wire_as_strings(self):
        # A JSON number is a double in the browser. Sent as numbers, 156337.55
        # can arrive as 156337.549999 and a comparison the backend called equal
        # becomes a difference on screen.
        _, body = self.get("/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk)

        for row in body["disagreements"]:
            for key in ("a_value", "b_value", "difference"):
                with self.subTest(row=row["key"], field=key):
                    self.assertIsInstance(row[key], (str, type(None)))

    def test_counts_are_unfiltered_so_the_filter_can_show_them(self):
        _, body = self.get(
            "/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk,
            reason="MISSING_IN_B",
        )

        self.assertEqual(len(body["disagreements"]), 1)
        self.assertEqual(body["total"], 8, "total must describe the org, not the filter")
        counted = {row["reason"]: row["count"] for row in body["counts"]}
        self.assertEqual(counted["VALUE_MISMATCH"], 3)

    def test_every_reason_appears_in_the_counts_even_at_zero(self):
        _, body = self.get("/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk)

        self.assertEqual(len(body["counts"]), 6)
        self.assertTrue(all("label" in row for row in body["counts"]))

    def test_an_unknown_reason_is_a_400_not_an_ignored_filter(self):
        # Silently ignoring it shows every row while the user believes they are
        # looking at a filtered list.
        response, _ = self.get(
            "/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk, reason="NONSENSE",
        )
        self.assertEqual(response.status_code, 400)

    def test_sorting_by_value_orders_the_rows(self):
        _, ascending = self.get(
            "/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk, sort="value",
        )
        _, descending = self.get(
            "/api/discrepancies/", batch=self.batch.pk, org=self.org_a.pk, sort="-value",
        )

        def amounts(body):
            return [
                row["a_value"] or row["b_value"]
                for row in body["disagreements"]
                if row["a_value"] or row["b_value"]
            ]

        self.assertEqual(amounts(ascending), sorted(amounts(ascending), key=float))
        self.assertEqual(amounts(descending), sorted(amounts(descending), key=float, reverse=True))

    def test_orgs_requires_a_batch(self):
        response, _ = self.get("/api/orgs/")
        self.assertEqual(response.status_code, 400)

    def test_orgs_lists_the_batchs_orgs(self):
        _, body = self.get("/api/orgs/", batch=self.batch.pk)
        self.assertEqual(sorted(org["code"] for org in body["orgs"]), ["ORG-A", "ORG-B"])

    def test_batches_lists_batches_with_their_row_counts(self):
        _, body = self.get("/api/batches/")

        self.assertEqual(len(body["batches"]), 1)
        self.assertEqual(body["batches"][0]["records"], 120)
        self.assertEqual(body["batches"][0]["entries"], 121)

    def test_a_post_is_refused(self):
        # Read-only until stage 9 adds uploads, and an endpoint that quietly
        # accepts a method it does not implement is worse than one that refuses.
        self.assertEqual(self.client.post("/api/discrepancies/").status_code, 405)
