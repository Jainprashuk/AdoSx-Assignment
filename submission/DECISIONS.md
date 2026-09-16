# Decisions

Ten decisions, each with the alternative rejected and the one line of
reasoning that separated them. Written as each stage happened, not
reconstructed at the end.

---

## 1. Surrogate primary keys, not natural ones

`record_id`, `entry_id`, `location_code` and `org_code` are indexed columns.
Every table has an auto integer primary key.

**Rejected:** natural keys, with an upsert on conflict.

**Reasoning:** a natural key declares the identifier unique, so a duplicate in
a dirty file forces either an aborted import or a skipped row — and the skipped
row is the silent drop the brief rules out.

---

## 2. No foreign key from entry to record

`Entry` stores `record_ref_raw` and an indexed `record_ref_norm`. Matching is a
join on the normalised string at comparison time.

**Rejected:** a nullable foreign key.

**Reasoning:** "an entry pointing at a record that does not exist" is a
required finding, and a foreign key — nullable or not — makes that row
physically unwritable, because the referenced row was never there.

---

## 3. Every parsed value is stored twice

Each value column is a pair: a nullable typed column and the original text.

**Rejected:** a single nullable typed column.

**Reasoning:** one column collapses "the source said N/A" and "the source said
nothing" into the same NULL, and those are different facts — the first is a
parse failure to report, the second is an empty cell.

---

## 4. Batch as the outermost scope

Every table carries a batch foreign key. Nothing is matched, joined or compared
across batches.

**Rejected:** one global dataset, replaced or merged on each import.

**Reasoning:** merging needs rules for the same `record_id` arriving twice with
different values, which the brief never defines; replacing means a reviewer's
upload destroys the sample data.

---

## 5. Normalisation fixes how a reference is written, never what it says

`rec1034`, `" REC - 1070 "` and `1112` all resolve. `REC-1999` stays itself and
is reported as an orphan.

**Rejected:** leaving the bare-digit reference unmatched as the cautious option.

**Reasoning:** every identifier in system A is `REC-` plus four digits, so
`1112` has one possible meaning — and refusing it produces two wrong findings
(a false orphan and a false missing entry) rather than one cautious non-answer.

---

## 6. Money is Decimal from the CSV cell to the browser

Parsed as `Decimal`, stored as `DecimalField`, compared quantised to the cent,
serialised as JSON strings, and never converted to a number in JavaScript.

**Rejected:** floats in the database, or JSON numbers on the wire.

**Reasoning:** a float makes two equal values unequal, and the false mismatches
it generates are indistinguishable from the real ones the project exists to
find — including at the last step, where a JSON number becomes a double in the
browser.

---

## 7. One finding per record, by precedence

Missing → duplicate → uncomparable → value mismatch → cross-org. A record that
breaks several rules produces one row.

**Rejected:** one row per rule broken.

**Reasoning:** the screen leads with a count of disagreements, and a record
entered twice with differing values is one problem to investigate, not two.

---

## 8. An entry belongs to the org of the record it references

Scoping follows the record; an entry falls back to its own location's org only
when the reference resolves to nothing.

**Rejected:** scoping records and entries independently, each by its own
location's org.

**Reasoning:** the rejected rule is the obvious one and it is wrong on the row
that tests it — REC-1077's entry is filed at an ORG-B location against an ORG-A
record, so scoping each side separately gives ORG-A a record with no entry and
ORG-B an orphan entry: two fabricated findings, and the real boundary crossing
reported to nobody.

---

## 9. A request that does not name one batch and one org is refused

`load_org_view` is the only way rows reach the comparison, and both arguments
are required. Missing, unknown or cross-batch is a 400.

**Rejected:** defaulting to the newest batch and the first org.

**Reasoning:** a default makes tenancy depend on the caller remembering to
override it, and the failure is silent — a forgotten parameter returns someone
else's rows with a 200.

---

## 10. Findings stop where the brief's rules stop

REC-1019 is `VOIDED` with a matching entry and is not reported. REC-1055's two
entries sum exactly to system A's total and are still reported as a duplicate,
with the sum stated in the detail.

**Rejected:** flagging the voided record; accepting the sum as reconciled.

**Reasoning:** neither file states that a voided record may not have an entry,
and nothing defines a rule for splitting a value across entries — so one would
report a disagreement where the systems agree, and the other would hide a
genuine double-entry that happened to add up.
