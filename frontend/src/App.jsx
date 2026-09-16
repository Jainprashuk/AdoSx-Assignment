/**
 * Scaffold check: proves the dev server reaches Django through the proxy.
 *
 * Replaced by the disagreement screen in the next stage. It exists as its own
 * commit so that the screen's diff is the screen, not the screen plus a
 * toolchain.
 */
import { useEffect, useState } from 'react'
import { fetchBatches } from './api'

export default function App() {
  const [batches, setBatches] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchBatches().then((data) => setBatches(data.batches)).catch((e) => setError(e.message))
  }, [])

  if (error) return <main><h1>Reconciliation</h1><p>Could not reach the API: {error}</p></main>
  if (!batches) return <main><h1>Reconciliation</h1><p>Loading…</p></main>

  return (
    <main>
      <h1>Reconciliation</h1>
      <p>The API is reachable. {batches.length} batch(es) loaded.</p>
      <ul>
        {batches.map((batch) => (
          <li key={batch.id}>
            {batch.label} — {batch.records} records, {batch.entries} entries, {batch.issues} issues
          </li>
        ))}
      </ul>
    </main>
  )
}
