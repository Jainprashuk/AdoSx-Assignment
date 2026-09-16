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

  // All three or nothing. A batch built from two files would be missing either
  // its org mapping or a whole side of the comparison, and would report
  // confident nonsense rather than failing.
  const ready = SLOTS.every((slot) => files[slot.key])

  function choose(key, file) {
    setFiles((current) => ({ ...current, [key]: file }))
    setResult(null)
    setError(null)
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
      <p className="sub">
        All three files are loaded together as one batch. Existing batches are left alone.
      </p>

      {SLOTS.map((slot) => (
        <div className="filerow" key={slot.key}>
          <span className="id">{slot.name}</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => choose(slot.key, e.target.files[0] ?? null)}
          />
        </div>
      ))}

      <div className="actions">
        <button type="button" className="primary" disabled={!ready || busy} onClick={submit}>
          {busy ? 'Loading…' : 'Create batch'}
        </button>
        <span className="sub">
          {ready ? 'Creates a new batch.' : 'All three files are required.'}
        </span>
      </div>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="result">
          <h3>{result.batch.label} — batch {result.batch.id}</h3>
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

          {result.issues.length === 0 ? (
            <p className="sub">Every row imported cleanly.</p>
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
