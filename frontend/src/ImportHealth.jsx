/**
 * What the importer had to deal with, for this org's rows only.
 *
 * This is the evidence behind "nothing was silently dropped": every line is a
 * row that was kept, with what was wrong and what was done about it. It lists
 * successful normalisations as well as failures, because a value read through
 * its separators is otherwise invisible.
 *
 * Collapsed by default -- it supports the table rather than competing with it.
 */
export default function ImportHealth({ issues }) {
  if (issues.length === 0) {
    return (
      <p className="health-empty">
        <span aria-hidden="true">✓</span> Every row in this org imported cleanly.
      </p>
    )
  }

  return (
    <details className="health">
      <summary>
        <strong>{issues.length}</strong>{' '}
        {issues.length === 1 ? 'row needed' : 'rows needed'} attention on import — kept, not dropped
      </summary>
      <ul>
        {issues.map((issue) => (
          <li key={`${issue.source_file}:${issue.line_number}:${issue.field}`}>
            <span className="id">{issue.source_file}:{issue.line_number}</span>
            <span>
              <code>{issue.field}</code> = <code>{issue.raw_value || '(blank)'}</code> — {issue.problem}
            </span>
          </li>
        ))}
      </ul>
    </details>
  )
}
