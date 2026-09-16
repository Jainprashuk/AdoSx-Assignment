# Decisions

Each entry: the decision, the alternative rejected, and the line of reasoning
separating them. Written as the work happens, not reconstructed at the end.

---

## 1. Surrogate primary keys, not natural ones

`record_id`, `entry_id`, `location_code` and `org_code` are indexed columns, not
primary keys. Every table has an auto integer PK.

**Rejected:** natural keys, with an upsert on conflict.

**Why:** a natural PK declares the identifier unique, so a duplicate identifier
in the source forces either an aborted import or a skipped row — and a skipped
row is the silent drop the brief explicitly rules out. Upsert avoids the crash
by merging two rows the source file says are two rows, which is data loss with
better manners. As indexed data rather than identity, a duplicate becomes
something to detect and report.

---

## 2. No foreign key from Entry to Record

`Entry` carries `record_ref_raw` (the text as written) and `record_ref_norm`
(normalised, indexed). Matching happens at comparison time, as a join on the
normalised string.

**Rejected:** a nullable `ForeignKey` with `on_delete=SET_NULL`.

**Why:** "an entry pointing at a record that does not exist" is one of the four
findings the brief requires, and a foreign key makes that row physically
unwritable — nullable or not, since the referenced row was never there to begin
with. The relationship is real; it lives in the query rather than in the
constraint. `location_code_raw` plus a nullable `location` FK follows the same
pattern for the same reason.

---

## 3. Every parsed value is stored twice

Each value column is a pair: a nullable typed column and a raw text column
holding the original characters.

| `total_value` | `total_value_raw` | Meaning |
|---|---|---|
| `88969.92` | `88969.92` | parsed cleanly |
| `125400.00` | `1,25,400.00` | parsed after normalising separators |
| `NULL` | `N/A` | present but unreadable |
| `NULL` | `` (empty) | genuinely blank in the source |

**Rejected:** a single nullable typed column, with a `FloatField` as the
variant considered for money.

**Why:** one nullable column collapses the last two rows of that table into the
same NULL, and "the source said something we could not read" is a different fact
from "the source said nothing" — the first is a parse failure worth reporting,
the second is just an empty cell. Keeping the raw text makes the distinction
derivable without a flag column, and it drives both the fifth comparison reason
and the way an unreadable value renders on screen. Float was rejected outright:
two values that should be equal stop being equal, and false mismatches are
indistinguishable from the real ones this project exists to find.

---

## 4. Import problems in their own table

`ImportIssue` records batch, source file, line number, field, raw value and a
human-readable description of what happened.

**Rejected:** a JSON column on each row holding that row's problems.

**Why:** some problems belong to no single row — a header mismatch, a line with
the wrong column count, a duplicate identifier concerning two rows at once — and
a per-row column has nowhere to put them. Keyed by file and line number instead,
which is the coordinate a human uses when they open the CSV to check. It also
makes "nothing was silently dropped" one query rather than a scan across two
tables.

---

## 5. Batch as the outermost scope

Every table carries a batch foreign key. A batch is one import run, and nothing
is matched, joined or compared across batches.

**Rejected:** a single global dataset, replaced or merged on each import.

**Why:** merging raises questions the brief never answers — what to do when the
same `record_id` arrives twice with different values — and replacing means a
reviewer uploading their own files destroys the seeded sample data. As separate
closed worlds there are no merge rules to invent and no conflict category to
define. It is also why uniqueness, where it exists at all, is scoped to the
batch rather than global.
