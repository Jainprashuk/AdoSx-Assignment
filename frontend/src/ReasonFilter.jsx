/**
 * The reason filter: one chip per reason, each carrying its count.
 *
 * Every reason is listed, including those with no rows, so the screen says what
 * it looks for rather than only what it happened to find. A reason at zero is
 * information: it means that kind of disagreement was checked for and is absent.
 */
export default function ReasonFilter({ counts, selected, onSelect }) {
  const total = counts.reduce((sum, item) => sum + item.count, 0)

  return (
    <div className="chips" role="group" aria-label="Filter by reason">
      <button
        type="button"
        className="chip"
        aria-pressed={selected === null}
        onClick={() => onSelect(null)}
      >
        All reasons <span className="count">{total}</span>
      </button>
      {counts.map((item) => (
        <button
          key={item.reason}
          type="button"
          className="chip"
          aria-pressed={selected === item.reason}
          // Clicking the active chip clears the filter, so there is always a
          // way back to the full list without hunting for a reset control.
          onClick={() => onSelect(selected === item.reason ? null : item.reason)}
          disabled={item.count === 0}
          // A greyed chip that does nothing when clicked has to say why, or it
          // reads as broken rather than as an answer.
          title={item.count === 0
            ? `Checked for — no ${item.label.toLowerCase()} in this org`
            : `Show only ${item.label.toLowerCase()}`}
        >
          {item.label} <span className="count">{item.count}</span>
        </button>
      ))}
    </div>
  )
}
