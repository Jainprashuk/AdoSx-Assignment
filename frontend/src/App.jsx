/**
 * The disagreement screen.
 *
 * One screen, so state lives here and is passed down: three selections (batch,
 * org, reason), one sort, and whatever the API last returned. A store would be
 * machinery for four values that only this component sets.
 *
 * Every fetch names a batch and an org. The API refuses a request that does
 * not, so there is no state in which this screen shows rows without knowing
 * whose they are.
 */
import { useCallback, useEffect, useState } from 'react'
import { fetchBatches, fetchDiscrepancies, fetchOrgs } from './api'
import DisagreementTable from './DisagreementTable'
import ImportHealth from './ImportHealth'
import ReasonFilter from './ReasonFilter'

export default function App() {
  const [batches, setBatches] = useState([])
  const [batch, setBatch] = useState(null)
  const [orgs, setOrgs] = useState([])
  const [org, setOrg] = useState(null)
  const [reason, setReason] = useState(null)
  const [sort, setSort] = useState(null)
  const [view, setView] = useState(null)
  const [error, setError] = useState(null)

  // Newest batch first, so the default selection is the most recent import.
  useEffect(() => {
    fetchBatches()
      .then((data) => {
        setBatches(data.batches)
        setBatch(data.batches[0]?.id ?? null)
      })
      .catch((e) => setError(e.message))
  }, [])

  // Orgs belong to a batch, so the list is refetched whenever the batch
  // changes and the first one is selected.
  useEffect(() => {
    if (batch === null) return
    fetchOrgs(batch)
      .then((data) => {
        setOrgs(data.orgs)
        setOrg(data.orgs[0]?.id ?? null)
      })
      .catch((e) => setError(e.message))
  }, [batch])

  const load = useCallback(() => {
    if (batch === null || org === null) return
    fetchDiscrepancies({ batch, org, reason, sort })
      // The error clears on success rather than before the request, so a
      // failed load leaves its message on screen until something works.
      .then((data) => { setView(data); setError(null) })
      .catch((e) => setError(e.message))
  }, [batch, org, reason, sort])

  useEffect(load, [load])

  // Changing batch or org clears what is on screen in the same event that
  // changes the selection, rather than in an effect afterwards. That ordering
  // is what stops the previous org's rows being visible for a frame under the
  // new org's name -- brief, but it would be one tenant's data displayed under
  // another's label, which is the one thing this screen must never do.
  function selectBatch(id) {
    setBatch(id)
    setOrg(null)
    setOrgs([])
    setReason(null)
    setSort(null)
    setView(null)
  }

  function selectOrg(id) {
    setOrg(id)
    setReason(null)
    setView(null)
  }

  // Belt and braces: never render a response that describes a different org
  // than the one currently selected.
  const current = view && view.org.id === org ? view : null

  return (
    <main>
      <header>
        <h1>Reconciliation</h1>
        <p className="sub">Records where system A and system B do not agree.</p>
      </header>

      <div className="controls">
        <label>
          Import batch
          <select value={batch ?? ''} onChange={(e) => selectBatch(Number(e.target.value))}>
            {batches.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </label>

        <label>
          Organisation
          <select
            value={org ?? ''}
            onChange={(e) => selectOrg(Number(e.target.value))}
            disabled={orgs.length === 0}
          >
            {orgs.map((item) => (
              <option key={item.id} value={item.id}>{item.code}</option>
            ))}
          </select>
        </label>

        <div className="total">
          <strong>{current ? current.total : '—'}</strong>
          <span>{current && current.total === 1 ? 'disagreement' : 'disagreements'}</span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {current && (
        <>
          {/* Counts come from the unfiltered view, so each chip says how many
              rows choosing it would give rather than how many are showing. */}
          <ReasonFilter counts={current.counts} selected={reason} onSelect={setReason} />
          <DisagreementTable
            rows={current.disagreements}
            sort={sort}
            onSortChange={setSort}
          />
          <ImportHealth issues={current.issues} />
        </>
      )}
    </main>
  )
}
