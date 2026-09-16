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
import Guide from './Guide'
import ImportHealth from './ImportHealth'
import LoadData from './LoadData'
import ReasonFilter from './ReasonFilter'
import { batchLabel } from './format'

export default function App() {
  const [batches, setBatches] = useState([])
  const [batch, setBatch] = useState(null)
  const [orgs, setOrgs] = useState([])
  const [org, setOrg] = useState(null)
  const [reason, setReason] = useState(null)
  const [sort, setSort] = useState(null)
  const [view, setView] = useState(null)
  const [error, setError] = useState(null)
  const [screen, setScreen] = useState('review')
  // Two distinct waits, because they mean different things on screen: the
  // batch list has not arrived yet, or rows are being fetched. Collapsing them
  // into one would show "no batches yet" during the first half second, which
  // is a statement about the data rather than about the network.
  const [booting, setBooting] = useState(true)
  // Which selection the response on screen belongs to. Derived rather than a
  // flag set at the top of the fetch: "loading" is exactly "what is shown is
  // not what is selected", and computing it from the two says so directly
  // instead of leaving a boolean to be turned off on every exit path.
  const [settled, setSettled] = useState(null)
  const wanted = `${batch}:${org}:${reason ?? ''}:${sort ?? ''}`
  const loading = batch !== null && org !== null && settled !== wanted

  // Newest batch first, so the default selection is the most recent import --
  // which, after an upload, is the batch just created.
  //
  // Goes through selectBatch rather than setBatch: an org id belongs to one
  // batch, so changing the batch without clearing the org sends a request
  // pairing the new batch with the previous batch's org. The API refuses that
  // pairing, which is correct, but the refusal is a visible error for
  // something the user never did.
  const loadBatches = useCallback(() => {
    fetchBatches()
      .then((data) => {
        setBatches(data.batches)
        selectBatch(data.batches[0]?.id ?? null)
        setError(null)
      })
      .catch((e) => setError(e.message))
      .finally(() => setBooting(false))
  }, [])

  useEffect(loadBatches, [loadBatches])

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
    // Every fetch is numbered, and only the newest one is allowed to write.
    // Switching org twice quickly otherwise lets the first response land after
    // the second and paint one tenant's rows under the other's name.
    let current = true
    const key = `${batch}:${org}:${reason ?? ''}:${sort ?? ''}`
    fetchDiscrepancies({ batch, org, reason, sort })
      // The error clears on success rather than before the request, so a
      // failed load leaves its message on screen until something works.
      .then((data) => { if (current) { setView(data); setError(null) } })
      .catch((e) => { if (current) setError(e.message) })
      // Settled on failure too. A request that errored is finished waiting,
      // and leaving the skeleton up under the error message would say it is
      // still trying when nothing is in flight.
      .finally(() => { if (current) setSettled(key) })
    return () => { current = false }
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
  const noBatches = !booting && batches.length === 0

  return (
    <main>
      <header>
        <div className="brand">
          <span className="mark" aria-hidden="true">
            {/* Two rules that do not line up: the application, in nine pixels. */}
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <path d="M2 5.5h9M8.5 3 11 5.5 8.5 8" />
              <path d="M14 10.5H5M7.5 8 5 10.5 7.5 13" />
            </svg>
          </span>
          <div>
            <h1>Reconciliation</h1>
            <p className="sub">Records where system A and system B do not agree.</p>
          </div>
        </div>

        <nav aria-label="Screens">
          <button
            type="button"
            aria-current={screen === 'review'}
            onClick={() => setScreen('review')}
          >
            Disagreements
          </button>
          <button
            type="button"
            aria-current={screen === 'load'}
            onClick={() => setScreen('load')}
          >
            Load data
          </button>
        </nav>
      </header>

      {/* Outside both screens: a batch list that failed to load is the reason
          the upload screen's selector is empty too, so the message has to
          survive switching screens. */}
      {error && (
        <p className="error" role="alert">
          <span>{error}</span>
          <button type="button" className="link" onClick={loadBatches}>Retry</button>
        </p>
      )}

      {screen === 'load' && (
        <LoadData
          // Refresh the selector so the new batch is there and selected -- it
          // sorts first, being the newest, and the existing batches are
          // untouched. The screen deliberately does not switch: the import
          // summary is the point of the upload, and navigating away from it
          // would throw away the evidence that nothing was dropped.
          onLoaded={loadBatches}
        />
      )}

      {screen === 'review' && (
      <>
      {/* Above the controls rather than below the table: it explains the
          controls, and an explanation you reach by scrolling past the thing it
          explains has already failed. Collapsed, so it costs one line. */}
      <Guide counts={current?.counts} />

      {noBatches ? (
        // Nothing has been imported yet. Saying so, and pointing at the screen
        // that fixes it, beats two empty dropdowns above an empty table.
        <div className="panel">
          <p><strong>No import batches yet</strong></p>
          <p>
            Load the three CSVs on the{' '}
            <button type="button" className="link" onClick={() => setScreen('load')}>Load data</button>
            {' '}screen to compare them.
          </p>
        </div>
      ) : (
      <>
      <div className="controls">
        <label>
          Import batch
          <select
            value={batch ?? ''}
            onChange={(e) => selectBatch(Number(e.target.value))}
            disabled={batches.length === 0}
          >
            {batches.map((item) => (
              <option key={item.id} value={item.id}>{batchLabel(item)}</option>
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

        {/* Announced, because the count is the answer to the question the
            screen exists to ask, and changing org changes it silently. */}
        <div className="total" aria-live="polite">
          <strong>{current ? current.total : '—'}</strong>
          <span>{current && current.total === 1 ? 'disagreement' : 'disagreements'}</span>
        </div>
      </div>

      {/* Chips stay mounted while rows reload, so the filter that triggered
          the load does not vanish underneath the cursor that clicked it. */}
      {current && (
        <ReasonFilter counts={current.counts} selected={reason} onSelect={setReason} />
      )}

      {!current && (loading || booting) && (
        <div className="table-wrap" aria-busy="true">
          <div className="skeleton" aria-label="Loading disagreements">
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
          </div>
        </div>
      )}

      {current && (
        // Dimmed rather than replaced while a filter or sort reloads: the rows
        // on screen are still the right org's, and swapping them for a
        // skeleton on every chip click makes the list flash for no new
        // information.
        <div className={loading ? 'busy' : undefined}>
          <DisagreementTable
            rows={current.disagreements}
            sort={sort}
            reason={reason}
            onSortChange={setSort}
            onClearFilter={() => setReason(null)}
          />
          <ImportHealth issues={current.issues} />
        </div>
      )}
      </>
      )}
      </>
      )}
    </main>
  )
}
