# Reconciliation — system A vs system B

## Submission

- [submission/README.md](submission/README.md) — how to run, what it does, API surface
- [submission/DECISIONS.md](submission/DECISIONS.md) — the ten decisions and the alternatives rejected

---

Finds the records where two systems disagree, one tenant at a time.

Two systems record the same events. They agree on most rows. This finds the
ones they do not agree on, says why, and never shows one org's rows to another.

---

## How to run

Requires Python 3.11+ and Node 18+. Two terminals.

**Backend**

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_data      # loads the three CSVs in backend/data
.venv/bin/python manage.py runserver        # http://127.0.0.1:8000
```

`import_data` is idempotent: running it again replaces its own batch rather
than loading a second copy.

**Frontend**

```bash
cd frontend
npm install
npm run dev                                  # open the URL it prints
```

Vite proxies `/api` to Django, so the browser sees one origin and there is no
CORS setup. If port 5173 is taken it will pick another — read the port it
prints.

**Tests**

```bash
cd backend && .venv/bin/python manage.py test reconciliation
```

100 tests. The comparison and parsing tests need no database.

---

## What the data contains

Everything below was found by reading the files, and each one is pinned by a
test so a change in the data fails a test rather than appearing on screen.

| | |
|---|---|
| Records with no entry | REC-1015, REC-1061 |
| Entry pointing at no record | REC-1999 (`ENT/2026/4901`) |
| Records entered twice | REC-1042 (identical values), REC-1055 (split, sums to system A's total) |
| Different values | REC-1003, REC-1027, REC-1064, REC-1088 |
| Value that cannot be compared | REC-1050 (system B blank) |
| Entry filed against another org's record | REC-1077 |
| References written three ways | `rec1034`, `" REC - 1070 "`, `1112` |
| Value needing its separators stripped | `1,25,400.00` |

11 disagreements: 8 in ORG-A, 3 in ORG-B. In three of the four value
mismatches, system B's value is exactly system A's `base_value` — system B
recorded the amount before adjustment.

---

## What was built

**Ingestion that keeps every row.** The importer's contract is that every data
line in every file becomes exactly one row, however bad the line is. A value
that cannot be read leaves the typed column null, keeps the original text, and
logs a note. The check that rows written equals rows read runs inside the
transaction, so a drop would roll the import back rather than produce a
plausible-looking screen. One thing aborts an import: a location mapped to two
different orgs, because that makes tenancy depend on row order.

**A schema that can hold the mess.** Surrogate keys, no foreign key from entry
to record, and every parsed value stored alongside its original text. Each of
those exists because a constraint the database enforces is a row the importer
cannot write, and the defects in this data *are* the deliverable.

**Comparison as pure functions.** `compare.py` imports nothing from Django and
touches no database — it takes dataclasses and returns findings. Six reasons:
the brief's four, plus `UNCOMPARABLE` (one side has no usable value) and
`CROSS_ORG_ENTRY` (an entry filed against another org's record).

**Tenancy in one function.** Every read goes through `load_org_view()`, which
requires a batch and an org and refuses anything else with a 400. Import issues
are attributed to an org before being displayed, because they carry raw text
copied out of source rows.

**A screen.** Batch and org selectors, the table, filter by reason with counts,
sort by value, and a panel showing what the importer had to deal with. Plus an
upload that loads three CSVs as a new batch, reusing the ingestion function
unchanged.

**Tests where the disagreements are decided.** 100 in total: one per reason
proving it is caught, and a set proving the non-errors are *not* reported —
trailing zeros, grouping separators, reference spellings, a voided record, a
two-day date difference. A comparison that flags everything passes the first
half and is worthless.

---

## What was deliberately not built

- **Authentication.** The brief says skip it. What is here is *scoping*, not
  access control: anyone who can reach the API can name any org. The upload
  endpoint is `@csrf_exempt` for the same reason — CSRF protects a session, and
  there is no session. The moment a login exists, both of those change.
- **Comparison of anything but the value.** Dates, categories, actors and
  labels are stored and shown but never compared. `ENT/2026/4009` is recorded
  two days after its record's event date and is not reported.
- **A check that `base_value + adjustment == total_value`.** It holds
  throughout system A. An internal consistency check is a different question
  from the one asked.
- **Fuzzy matching between near-miss references.** `REC-1999` is reported as an
  orphan, not repaired into `REC-1099`. Repairing it would delete the finding.
- **Date-format fallbacks.** ISO only. `03/04/2026` is either 3 April or
  4 March, and guessing invents a fact. Both files are ISO throughout.
- **Pagination, caching, query tuning, bulk inserts.** 241 rows.
- **Frontend tests.** The brief asks for tests where the disagreements are
  decided; that is `compare.py`. A test asserting a table renders a list would
  not catch a regression that matters.
- **Batch deletion, drag-and-drop uploads, progress bars, CSS beyond the
  minimum.** Plain and working over pretty and broken.

---

## Decisions

Ten decisions, each with the alternative rejected and the reasoning that
separated them.

### 1. Surrogate primary keys, not natural ones

`record_id`, `entry_id`, `location_code` and `org_code` are indexed columns.
Every table has an auto integer primary key.

**Rejected:** natural keys, with an upsert on conflict.

**Reasoning:** a natural key declares the identifier unique, so a duplicate in
a dirty file forces either an aborted import or a skipped row — and the skipped
row is the silent drop the brief rules out.

---

### 2. No foreign key from entry to record

`Entry` stores `record_ref_raw` and an indexed `record_ref_norm`. Matching is a
join on the normalised string at comparison time.

**Rejected:** a nullable foreign key.

**Reasoning:** "an entry pointing at a record that does not exist" is a
required finding, and a foreign key — nullable or not — makes that row
physically unwritable, because the referenced row was never there.

---

### 3. Every parsed value is stored twice

Each value column is a pair: a nullable typed column and the original text.

**Rejected:** a single nullable typed column.

**Reasoning:** one column collapses "the source said N/A" and "the source said
nothing" into the same NULL, and those are different facts — the first is a
parse failure to report, the second is an empty cell.

---

### 4. Batch as the outermost scope

Every table carries a batch foreign key. Nothing is matched, joined or compared
across batches.

**Rejected:** one global dataset, replaced or merged on each import.

**Reasoning:** merging needs rules for the same `record_id` arriving twice with
different values, which the brief never defines; replacing means a reviewer's
upload destroys the sample data.

---

### 5. Normalisation fixes how a reference is written, never what it says

`rec1034`, `" REC - 1070 "` and `1112` all resolve. `REC-1999` stays itself and
is reported as an orphan.

**Rejected:** leaving the bare-digit reference unmatched as the cautious option.

**Reasoning:** every identifier in system A is `REC-` plus four digits, so
`1112` has one possible meaning — and refusing it produces two wrong findings
(a false orphan and a false missing entry) rather than one cautious non-answer.

---

### 6. Money is Decimal from the CSV cell to the browser

Parsed as `Decimal`, stored as `DecimalField`, compared quantised to the cent,
serialised as JSON strings, and never converted to a number in JavaScript.

**Rejected:** floats in the database, or JSON numbers on the wire.

**Reasoning:** a float makes two equal values unequal, and the false mismatches
it generates are indistinguishable from the real ones the project exists to
find — including at the last step, where a JSON number becomes a double in the
browser.

---

### 7. One finding per record, by precedence

Missing → duplicate → uncomparable → value mismatch → cross-org. A record that
breaks several rules produces one row.

**Rejected:** one row per rule broken.

**Reasoning:** the screen leads with a count of disagreements, and a record
entered twice with differing values is one problem to investigate, not two.

---

### 8. An entry belongs to the org of the record it references

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

### 9. A request that does not name one batch and one org is refused

`load_org_view` is the only way rows reach the comparison, and both arguments
are required. Missing, unknown or cross-batch is a 400.

**Rejected:** defaulting to the newest batch and the first org.

**Reasoning:** a default makes tenancy depend on the caller remembering to
override it, and the failure is silent — a forgotten parameter returns someone
else's rows with a 200.

---

### 10. Findings stop where the brief's rules stop

REC-1019 is `VOIDED` with a matching entry and is not reported. REC-1055's two
entries sum exactly to system A's total and are still reported as a duplicate,
with the sum stated in the detail.

**Rejected:** flagging the voided record; accepting the sum as reconciled.

**Reasoning:** neither file states that a voided record may not have an entry,
and nothing defines a rule for splitting a value across entries — so one would
report a disagreement where the systems agree, and the other would hide a
genuine double-entry that happened to add up.

---

## How I worked with the agent

I used Claude Code for essentially all of the code, working in eleven planned
stages. Before starting I wrote three documents the agent worked from: a schema
design, a working plan, and a working agreement covering comment style, scope
discipline, and a rule that the agent stops at the end of every stage and tells
me what to run to verify it.

Two habits did most of the work. The first was making the agent read the actual
CSVs before writing anything that touched them; the parsing stage was scoped by
a script that inventoried the real dirt, which is why there are no date-format
fallbacks or currency-symbol handling for data that does not exist. The second
was insisting that nothing enters the repo that I cannot explain, which killed
several suggestions — a denormalised `org_id` column, fuzzy reference matching
— that would have been faster to accept than to argue with.

Where the agent was most useful was in the argued parts: the cross-org scoping
rule, the precedence order between reasons, and the raw/typed column pairing
all got written down as decisions with rejected alternatives at the time, not
reconstructed afterwards. Where it needed the most checking was anything it
asserted confidently without running — see below.

---

### a. Name one thing the AI agent got wrong. How did you notice?

It set `on_delete=PROTECT` on the two location foreign keys, with a comment
arguing that locations are only ever deleted along with their batch, so the
cascade would reach records first and `PROTECT` would only fire on an
unexpected direct delete. The reasoning reads well. It is also wrong: Django's
collector gathers the whole object graph before deleting anything, so deleting
a batch collects its locations and hits the protected reference from records
that have not been deleted yet. A batch could not be deleted at all.

I found it because the seed command has to be idempotent, so my check for that
stage was to run `import_data` twice rather than once. The first run was clean;
the second died with `ProtectedError`. Reading the code would not have caught
it — the comment was confident, plausible and wrong, which is exactly the
failure mode worth planning for. It is now `SET_NULL` (migration `0002`), which
is also the more consistent choice, since a record with no location is already
a legal state in this schema.

That shaped how I checked everything afterwards: run the thing twice, run it
from a clean clone, and click the actual button. The last one paid off in the
final stage, where a hundred passing tests and a working API still hid two bugs
that only appeared in the browser.

### b. Which part of your submission are you least confident about, and why?

`CROSS_ORG_ENTRY`, the sixth reason — specifically which org's view it belongs
in, not whether it should exist.

REC-1077 is ORG-A's record with an entry filed at an ORG-B location, and the
two values agree, so every value-based rule stays silent. I am confident it has
to be found: the brief's one hard rule is that a row belonging to one tenant
must never be visible to another, and a boundary crossing that reconciles
cleanly is the worst thing this screen could miss. I am also confident the
obvious alternative is wrong, because I tried it — scoping each side by its own
location gives ORG-A a record with no entry and ORG-B an orphan entry: two
fabricated findings, and the real defect reported to nobody.

What I am less sure of is the call I made after that. I put the finding in the
record's org, on the grounds that system A is where the record exists, which
means ORG-A's screen names an ORG-B location code. That is a small disclosure
made in order to explain the finding, and a real tenant might reasonably want
it redacted. In production this is a question for whoever owns the tenancy
policy, and the code is arranged so that the answer changes one branch of
`_compare_pair` rather than the design around it.

### c. If you had a second day, what would you fix first?

Reconciliation state — the ability to mark a finding as reviewed, accepted or
escalated. As it stands the screen recomputes the same eleven findings on every
request, so the second person to open it learns nothing from the first. That is
the difference between a report and a tool, and it is the first thing anyone
using this daily would ask for. It is also a genuine design question rather
than plumbing: a note attaches to a finding, but findings are derived, so it
needs a decision about what happens when the same record reappears in a later
batch with a different value.

Three smaller things after that. In three of the four value mismatches, system
B's number is exactly system A's `base_value` — one systematic cause, almost
certainly a mapping error upstream, and the screen should surface that grouping
instead of leaving you to spot it by eye. `services.py` re-resolves every
import issue's owning org on each request, which is fine for five issues and
would not be at five thousand. And I would add one end-to-end test that drives
a browser, because both bugs my test suite missed lived in the gap between a
correct API and what the screen did with it.
