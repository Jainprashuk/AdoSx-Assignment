"""
Tables for one reconciliation run.

The governing idea: every constraint the database enforces is a row the importer
cannot write. The brief promises dirty data and requires that the importer
survive it without silently dropping rows, so this schema stores first and
resolves second. References that cross a file boundary are kept as text and
resolved to a foreign key only when they resolve; failure to resolve is a
finding, not an error.

What this deliberately does NOT do: enforce that an entry points at a real
record, that a location exists in the mapping file, that record identifiers are
unique, or that a value is a number. Each of those defects is something the
comparison stage has to report, so the schema has to be able to hold it.
"""

from django.db import models

# Money. Six integer digits covers the largest value in the sample (184,503.73)
# with room to spare; two decimal places is what both files use.
MONEY_DIGITS = 14
MONEY_PLACES = 2

# Raw columns hold the source text verbatim. Long enough that no source value is
# ever truncated -- a truncated raw value would be a silent alteration, which is
# the thing this schema exists to avoid.
RAW_LENGTH = 255


class Batch(models.Model):
    """One import run, and a closed world.

    Nothing is matched, joined or compared across batches. That is what lets a
    reviewer upload their own files without disturbing the seeded sample data,
    and it removes the need for merge rules the brief never defines: two batches
    containing REC-1001 are two unrelated rows, not a conflict.
    """

    label = models.CharField(max_length=RAW_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.label


class Org(models.Model):
    """A tenant.

    The brief's one hard rule is that a row belonging to one org must never be
    visible to another, so the boundary gets its own table rather than living as
    a string on Location. No name column: locations.csv gives org_id only, and
    inventing a display name would be fabricating data.
    """

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="orgs")
    org_code = models.CharField(max_length=RAW_LENGTH)

    class Meta:
        # Scoped to the batch, not global: a later import may describe the same
        # org codes, and those are separate rows.
        unique_together = [("batch", "org_code")]
        ordering = ["org_code"]

    def __str__(self) -> str:
        return self.org_code


class Location(models.Model):
    """The location-to-org mapping, which locations.csv is the only source of.

    Neither system_a.csv nor system_b.csv says who owns a row; they give a
    location code and nothing else. Every "whose record is this" question
    resolves through this table, which is why ingestion reads this file first.
    """

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="locations")
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="locations")
    location_code = models.CharField(max_length=RAW_LENGTH)
    # Present in locations.csv. Not used in comparison, kept because dropping a
    # column the source provides is discarding data for no reason.
    location_name = models.CharField(max_length=RAW_LENGTH, blank=True)

    class Meta:
        # The one place uniqueness is safe to enforce. A location mapped to two
        # different orgs is a genuine defect that should stop the import rather
        # than silently pick a winner -- a silent winner here is a tenancy bug.
        unique_together = [("batch", "location_code")]
        ordering = ["location_code"]

    def __str__(self) -> str:
        return self.location_code


class Record(models.Model):
    """One row of system_a.csv: the left-hand side of every comparison."""

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="records")

    # Indexed, NOT unique. Making record_id the primary key would declare it
    # unique; a duplicate identifier in the source would then force either an
    # aborted import or a skipped row, and the skipped row is exactly the silent
    # drop the brief rules out. Identity is the surrogate key; record_id is data.
    record_id = models.CharField(max_length=RAW_LENGTH, db_index=True)

    # The location as written, plus a nullable FK populated only when that text
    # matches this batch's mapping file. A code absent from locations.csv is a
    # finding, so it must not block the insert.
    location_code_raw = models.CharField(max_length=RAW_LENGTH, blank=True)
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="records"
    )

    # Every parsed field is stored twice: the typed value, and the original
    # characters. A single nullable column collapses "the source said N/A" and
    # "the source said nothing" into one NULL, and those are different facts.
    event_date = models.DateField(null=True, blank=True)
    event_date_raw = models.CharField(max_length=RAW_LENGTH, blank=True)

    category_code = models.CharField(max_length=RAW_LENGTH, blank=True)
    actor_id = models.CharField(max_length=RAW_LENGTH, blank=True)

    base_value = models.DecimalField(
        max_digits=MONEY_DIGITS, decimal_places=MONEY_PLACES, null=True, blank=True
    )
    base_value_raw = models.CharField(max_length=RAW_LENGTH, blank=True)

    adjustment = models.DecimalField(
        max_digits=MONEY_DIGITS, decimal_places=MONEY_PLACES, null=True, blank=True
    )
    adjustment_raw = models.CharField(max_length=RAW_LENGTH, blank=True)

    # The compared field. system_a's total_value against system_b's value.
    total_value = models.DecimalField(
        max_digits=MONEY_DIGITS, decimal_places=MONEY_PLACES, null=True, blank=True
    )
    total_value_raw = models.CharField(max_length=RAW_LENGTH, blank=True)

    # CONFIRMED or VOIDED in the sample. Carried through; not yet acted on.
    state = models.CharField(max_length=RAW_LENGTH, blank=True)

    # Line number in the CSV, so any finding can be traced back to a row a human
    # can open and look at.
    source_line = models.PositiveIntegerField()

    class Meta:
        indexes = [models.Index(fields=["batch", "record_id"])]
        ordering = ["record_id"]

    def __str__(self) -> str:
        return self.record_id


class Entry(models.Model):
    """One row of system_b.csv: the right-hand side of every comparison."""

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="entries")
    entry_id = models.CharField(max_length=RAW_LENGTH, db_index=True)

    # No ForeignKey to Record, by design. "An entry pointing at a record that
    # does not exist" is one of the four required findings, so a constraint
    # would make the row physically unwritable. The relationship lives in the
    # query instead: match on record_ref_norm at comparison time.
    record_ref_raw = models.CharField(max_length=RAW_LENGTH, blank=True)
    # The normalised form, stored rather than computed at read time so the match
    # is an index lookup and so the normalisation is visible in the data.
    record_ref_norm = models.CharField(max_length=RAW_LENGTH, blank=True, db_index=True)

    # Kept independently of the record's location: an entry whose location sits
    # in a different org than its record is how a cross-tenant pair becomes
    # detectable, and that is only visible if both sides are stored.
    location_code_raw = models.CharField(max_length=RAW_LENGTH, blank=True)
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="entries"
    )

    recorded_on = models.DateField(null=True, blank=True)
    recorded_on_raw = models.CharField(max_length=RAW_LENGTH, blank=True)

    # The compared field on system B's side.
    value = models.DecimalField(
        max_digits=MONEY_DIGITS, decimal_places=MONEY_PLACES, null=True, blank=True
    )
    value_raw = models.CharField(max_length=RAW_LENGTH, blank=True)

    label = models.CharField(max_length=RAW_LENGTH, blank=True)
    source_line = models.PositiveIntegerField()

    class Meta:
        # No uniqueness on (batch, record_ref_norm): "the same record entered
        # twice" is a required finding, so the schema must permit it.
        indexes = [models.Index(fields=["batch", "record_ref_norm"])]
        ordering = ["entry_id"]

    def __str__(self) -> str:
        return self.entry_id


class ImportIssue(models.Model):
    """One problem noticed while reading a file, kept as evidence.

    This is what makes "nothing was silently dropped" a number on screen rather
    than a claim in the README. It deliberately has no foreign key to the row it
    describes: some problems belong to no single row -- a header mismatch, a
    line with the wrong column count, a duplicate identifier concerning two rows
    at once. File and line number is the coordinate a human actually uses.
    """

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="issues")
    source_file = models.CharField(max_length=RAW_LENGTH)
    line_number = models.PositiveIntegerField()
    field = models.CharField(max_length=RAW_LENGTH, blank=True)
    raw_value = models.CharField(max_length=RAW_LENGTH, blank=True)
    # Written for a human to read, not parsed: what happened and what was done.
    problem = models.TextField()

    class Meta:
        indexes = [models.Index(fields=["batch"])]
        ordering = ["source_file", "line_number"]

    def __str__(self) -> str:
        return f"{self.source_file}:{self.line_number} {self.field}"
