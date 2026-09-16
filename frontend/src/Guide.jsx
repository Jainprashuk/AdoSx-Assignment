/**
 * What the screen does and how to read it.
 *
 * The table is dense and the six reasons are domain words: "orphan entry" and
 * "cannot be compared" mean something precise here and nothing obvious to
 * someone opening the page for the first time. Rather than shortening the
 * labels until they are vague, the meanings are written down once, next to
 * the thing they describe.
 *
 * Collapsed by default. Someone who already knows the six reasons should not
 * have to scroll past an explanation of them to reach the rows, and someone
 * who does not should not have to go looking in a README.
 */

// The label is the same string the API sends, so the glossary and the filter
// chips cannot drift apart -- `counts` overrides these when it has arrived.
// The meaning is local, because it is prose about the domain rather than data.
const REASONS = [
  {
    reason: 'MISSING_IN_B',
    label: 'Missing in system B',
    meaning: 'System A has the record. System B has no entry referencing it at all.',
  },
  {
    reason: 'ORPHAN_ENTRY',
    label: 'Entry with no record',
    meaning: 'The mirror image: system B filed an entry against a record that system A does not have.',
  },
  {
    reason: 'DUPLICATE_ENTRY',
    label: 'Entered twice',
    meaning: 'System B has more than one entry for the same record — either the same amount twice, or a split that may or may not sum to system A’s total. The detail line says which.',
  },
  {
    reason: 'VALUE_MISMATCH',
    label: 'Different values',
    meaning: 'Both systems have the record and both report an amount, but the amounts differ. The difference column says by how much.',
  },
  {
    reason: 'UNCOMPARABLE',
    label: 'Cannot be compared',
    meaning: 'Both sides exist, but at least one amount could not be read as a number, so no comparison is possible. The original characters are shown rather than guessed at.',
  },
  {
    reason: 'CROSS_ORG_ENTRY',
    label: 'Filed against another org',
    meaning: 'The amounts agree, but the entry is filed at a location belonging to a different organisation than the record. Worth seeing even though nothing is short.',
  },
]

export default function Guide({ counts }) {
  // Prefer the API's label for each reason when a response has arrived.
  const apiLabels = new Map((counts ?? []).map((item) => [item.reason, item.label]))

  return (
    <details className="guide">
      <summary>
        <span className="guide-icon" aria-hidden="true">?</span>
        What this screen does, and how to read it
      </summary>

      <div className="guide-body">
        <p>
          Two systems record the same events. They agree on most rows. This screen
          shows the ones they do not agree on, for <strong>one organisation at a
          time</strong> — an org’s rows are never mixed with another’s.
        </p>

        <h3>Using it</h3>
        <ol className="guide-steps">
          <li>
            <strong>Pick an import batch.</strong> Each upload of the three CSVs is
            its own batch and its own closed world. The newest is selected for you.
          </li>
          <li>
            <strong>Pick an organisation.</strong> Everything below — the count, the
            rows, the import notes — is that org’s and only that org’s.
          </li>
          <li>
            <strong>Narrow it down.</strong> Click a reason chip to see only that
            kind of disagreement; click it again to go back to all of them. A chip
            showing <span className="count">0</span> means that kind was checked for
            and none was found. Click <em>System A</em> to sort by amount.
          </li>
        </ol>

        <h3>What each reason means</h3>
        <dl className="guide-reasons">
          {REASONS.map((item) => (
            <div key={item.reason}>
              <dt><span className={`tag tag-${item.reason}`}>{apiLabels.get(item.reason) ?? item.label}</span></dt>
              <dd>{item.meaning}</dd>
            </div>
          ))}
        </dl>

        <h3>Reading the amounts</h3>
        <p>
          The three states in the System A and System B columns are deliberately
          different, because they are three different facts:
        </p>
        {/* Sample and meaning in two columns, same shape as the reason
            glossary. A prose list would put an em dash between the sample and
            its description, which is unreadable when the sample is itself an
            em dash. */}
        <dl className="guide-states">
          <div>
            <dt><span className="num">41,095.33</span></dt>
            <dd>The system reported this amount.</dd>
          </div>
          <div>
            <dt><span className="unreadable">N/A</span></dt>
            <dd>It reported something that is not a number. Shown exactly as written rather than treated as zero.</dd>
          </div>
          <div>
            <dt><span className="absent">—</span></dt>
            <dd>It reported nothing at all.</dd>
          </div>
        </dl>
        <p className="guide-note">
          Amounts are never converted to a floating-point number anywhere in this
          app, so what you see is exactly what was compared.
        </p>
      </div>
    </details>
  )
}
