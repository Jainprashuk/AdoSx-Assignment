/**
 * The table. One row per disagreement, with both systems' values side by side.
 *
 * The brief asks for the reason, both versions of the value, and the location.
 * The extra columns -- difference, entry ids, the detail line -- are there
 * because a reviewer looking at a row immediately asks "by how much" and
 * "which entries", and answering that in the row is cheaper than making them
 * go back to the CSV.
 */
import { groupDigits, isZeroAmount, valueCell } from './format'

function ValueCell({ value, raw }) {
  const cell = valueCell(value, raw)
  if (cell.state === 'unreadable') {
    // Shown as the original characters, marked as unreadable. An amber cell
    // saying "N/A" is a different fact from an empty one, and collapsing them
    // would hide a parse failure behind what looks like a missing value.
    return <span className="unreadable" title="stored as written; not a number">{cell.text}</span>
  }
  if (cell.state === 'absent') {
    return <span className="absent">{cell.text}</span>
  }
  return cell.text
}

export default function DisagreementTable({ rows, sort, onSortChange }) {
  if (rows.length === 0) {
    return <p className="empty">No disagreements match this filter.</p>
  }

  // Three-state toggle: ascending, descending, then back to the natural order
  // grouped by reason, which is the more useful default for scanning.
  const nextSort = sort === 'value' ? '-value' : sort === '-value' ? null : 'value'
  const caret = sort === 'value' ? ' ↑' : sort === '-value' ? ' ↓' : ''

  return (
    <table>
      <thead>
        <tr>
          <th>Record</th>
          <th>Reason</th>
          <th className="num sortable">
            <button type="button" onClick={() => onSortChange(nextSort)}>
              System A{caret}
            </button>
          </th>
          <th className="num">System B</th>
          <th className="num">Difference</th>
          <th>Location</th>
          <th>Entries</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          // An orphan entry has no record, so the reference it was written with
          // is the only identifier available -- and the one the reviewer needs.
          <tr key={`${row.reason}:${row.key}`}>
            <td className="id">
              {row.record_id ?? <span className="absent" title="no such record">{row.key}</span>}
            </td>
            <td>
              <span className={`tag tag-${row.reason}`}>{row.reason_label}</span>
              <div className="detail">{row.detail}</div>
            </td>
            <td className="num"><ValueCell value={row.a_value} raw={row.a_value_raw} /></td>
            <td className="num"><ValueCell value={row.b_value} raw={row.b_value_raw} /></td>
            {/* A difference of zero is not a gap: the cross-org finding has
                matching values, and colouring its 0.00 like a shortfall would
                say the amounts disagree when the whole point is that they do
                not. */}
            <td className={isZeroAmount(row.difference) ? 'num' : 'num difference'}>
              {row.difference === null
                ? <span className="absent">—</span>
                : groupDigits(row.difference)}
            </td>
            <td className="id">{row.location_code}</td>
            <td className="id entries">
              {row.entry_ids.length === 0
                ? <span className="absent">none</span>
                : row.entry_ids.map((id) => <div key={id}>{id}</div>)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
