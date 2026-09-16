/**
 * The one place the app talks to the backend.
 *
 * Every amount arrives as a string and stays one. Nothing here parses money
 * into a Number: the backend compared these values as decimals, and turning
 * them into floats to display them would reintroduce exactly the rounding the
 * whole backend was built to avoid.
 */

// Relative, because the dev server proxies /api to Django. No base URL to
// configure, and nothing to change between running locally and being served
// from the same origin in a build.
const API = '/api'

async function get(path, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== null && value !== undefined && value !== ''),
  )
  const url = query.toString() ? `${API}${path}?${query}` : `${API}${path}`

  const response = await fetch(url)
  const body = await response.json().catch(() => ({}))

  if (!response.ok) {
    // The API says why in `error` -- a missing org, an unknown reason. Showing
    // that text is more useful than a status code, and these are the messages
    // that prove a request was refused rather than quietly answered.
    throw new Error(body.error || `Request failed (${response.status})`)
  }
  return body
}

export const fetchBatches = () => get('/batches/')

/**
 * Upload three CSVs as a new batch.
 *
 * multipart/form-data with no Content-Type set by hand: the browser has to add
 * the multipart boundary itself, and setting the header manually omits it.
 * The field names are the filenames the brief uses, which is what the backend
 * looks for.
 */
export async function uploadBatch(files) {
  const form = new FormData()
  form.append('locations.csv', files.locations)
  form.append('system_a.csv', files.systemA)
  form.append('system_b.csv', files.systemB)

  const response = await fetch(`${API}/batches/`, { method: 'POST', body: form })
  const body = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new Error(body.error || `Upload failed (${response.status})`)
  }
  return body
}

export const fetchOrgs = (batch) => get('/orgs/', { batch })

// batch and org are required by the API. Passing either as undefined gets a 400
// rather than someone else's rows, which is the point.
export const fetchDiscrepancies = ({ batch, org, reason, sort }) =>
  get('/discrepancies/', { batch, org, reason, sort })
