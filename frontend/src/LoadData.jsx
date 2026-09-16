/**
 * Upload three CSVs as a new batch.
 *
 * Deliberately not a general import screen: the three files are fixed and
 * named, because the brief's data is three fixed files. The response is shown
 * in full -- per-file row counts and every logged problem -- since the claim
 * worth making about this importer is that nothing was dropped, and the
 * evidence for that is the numbers matching and the issues being listed.
 */
import { useState } from 'react'
import { uploadBatch } from './api'
import { fileSize } from './format'

const SLOTS = [
  { key: 'locations', name: 'locations.csv' },
  { key: 'systemA', name: 'system_a.csv' },
  { key: 'systemB', name: 'system_b.csv' },
]

export default function LoadData({ onLoaded }) {
  const [files, setFiles] = useState({ locations: null, systemA: null, systemB: null })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  // Which slot a drag is currently over. One key rather than a flag per slot,
  // because a pointer is only ever over one of them.
  const [over, setOver] = useState(null)

  // All three or nothing. A batch built from two files would be missing either
  // its org mapping or a whole side of the comparison, and would report
  // confident nonsense rather than failing.
  const ready = SLOTS.every((slot) => files[slot.key])
  const chosen = SLOTS.filter((slot) => files[slot.key]).length

  function choose(key, file) {
    setFiles((current) => ({ ...current, [key]: file }))
    setResult(null)
    setError(null)
  }

  // A drop lands in the slot it was dropped on, whatever the file is called.
  // The slot decides which of the three the file is, so a CSV exported under
  // some other name still imports instead of being silently refused.
  function drop(event, key) {
    event.preventDefault()
    setOver(null)
    const file = event.dataTransfer.files[0]
    if (file) choose(key, file)
  }

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const body = await uploadBatch(files)
      setResult(body)
      // The new batch has to appear in the selector, and the existing ones
      // have to still be there -- batches are closed worlds.
      onLoaded()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="load">
      <h2>Load data</h2>
      {/* What a batch is, before asking for three files. Someone uploading for
          the first time needs to know that this adds a world rather than
          replacing the one they were just looking at. */}
      <p className="sub">
        The three files are imported together as one <strong>batch</strong> — a
        self-contained snapshot that is compared only against itself. Existing
        batches are left exactly as they are, and the new one becomes the
        selected batch on the Disagreements screen.
      </p>
      <p className="sub">
        Every row is kept. Anything the importer had to work around — a blank
        amount, a value it could not read, a reference to a location it does not
        know — is reported below rather than dropped.
      </p>

      <div className="slots">
        {SLOTS.map((slot) => {
          const file = files[slot.key]
          return (
            <div
              key={slot.key}
              className={`slot${file ? ' filled' : ''}${over === slot.key ? ' over' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setOver(slot.key) }}
              onDragLeave={() => setOver((k) => (k === slot.key ? null : k))}
              onDrop={(e) => drop(e, slot.key)}
            >
              <span className="slot-name">{slot.name}</span>

              <span className="slot-state">
                {file ? (
                  <>
                    {/* The chosen file's own name, not the slot's: they are
                        often different, and showing the slot's name back would
                        hide a file dropped into the wrong row. */}
                    <span className="slot-file" title={file.name}>{file.name}</span>
                    <span className="slot-size">{fileSize(file.size)}</span>
                  </>
                ) : (
                  over === slot.key ? 'Drop to use this file' : 'Drop a CSV here, or'
                )}
              </span>

              <label className="slot-pick">
                {file ? 'Replace' : 'Choose file'}
                <input
                  type="file"
                  accept=".csv,text/csv"
                  aria-label={`${slot.name} — choose file`}
                  onChange={(e) => choose(slot.key, e.target.files[0] ?? null)}
                />
              </label>

              {file && (
                <button
                  type="button"
                  className="slot-clear"
                  aria-label={`Remove the file chosen for ${slot.name}`}
                  onClick={() => choose(slot.key, null)}
                >
                  ✕
                </button>
              )}
            </div>
          )
        })}
      </div>

      <div className="actions">
        <button type="button" className="primary" disabled={!ready || busy} onClick={submit}>
          {busy ? 'Loading…' : 'Create batch'}
        </button>
        {/* Says what is still missing, not just that something is. */}
        <span className="sub">
          {ready ? 'Creates a new batch.' : `${chosen} of 3 files chosen — all three are required.`}
        </span>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      {result && (
        <div className="result">
          <h3>{result.batch.label} — batch {result.batch.id}</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>File</th><th className="num">Rows read</th><th className="num">Rows written</th><th className="num">Issues</th></tr>
              </thead>
              <tbody>
                {result.files.map((file) => (
                  <tr key={file.name}>
                    <td className="id">{file.name}</td>
                    <td className="num">{file.rows_read}</td>
                    {/* Read and written must match. They are shown side by side
                        rather than as a tick, so the claim can be checked
                        instead of believed. */}
                    <td className="num">{file.rows_written}</td>
                    <td className="num">{file.issues}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {result.issues.length === 0 ? (
            <p className="ok-note"><span aria-hidden="true">✓</span> Every row imported cleanly.</p>
          ) : (
            <ul className="issues">
              {result.issues.map((issue) => (
                <li key={`${issue.source_file}:${issue.line_number}:${issue.field}`}>
                  <span className="id">{issue.source_file}:{issue.line_number}</span>
                  <span>
                    <code>{issue.field}</code> = <code>{issue.raw_value || '(blank)'}</code> — {issue.problem}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
