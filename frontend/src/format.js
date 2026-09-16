/**
 * Display helpers.
 *
 * Amounts arrive from the API as strings and are never converted to Number,
 * here or anywhere else. Grouping the digits is done on the string itself, so
 * a value that the backend compared as a Decimal is displayed as exactly the
 * characters it sent -- no rounding, no 156337.549999.
 */

/** Group the integer digits of a decimal string: "183244.16" -> "183,244.16". */
export function groupDigits(amount) {
  const [whole, fraction] = String(amount).split('.')
  const sign = whole.startsWith('-') ? '-' : ''
  const digits = sign ? whole.slice(1) : whole
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return fraction ? `${sign}${grouped}.${fraction}` : `${sign}${grouped}`
}

/** True for "0", "0.00", "-0.00" and so on. A string test, not Number(): the
 *  rule that money never becomes a JavaScript number holds here too, even
 *  though a zero check would survive the conversion. One exception is how the
 *  rule stops being a rule. */
export function isZeroAmount(amount) {
  return amount !== null && amount !== undefined && /^-?0(\.0*)?$/.test(String(amount))
}

/**
 * What a value cell should show, and which of three states it is in.
 *
 * The three are deliberately distinct on screen, because they are three
 * different facts and the second is the one a reviewer needs to notice:
 *
 *   value      the system reported an amount
 *   unreadable the system reported something that is not a number
 *   absent     the system reported nothing at all
 */
export function valueCell(value, raw) {
  if (value !== null && value !== undefined) {
    return { state: 'value', text: groupDigits(value) }
  }
  if (raw && raw.trim() !== '') {
    return { state: 'unreadable', text: raw.trim() }
  }
  return { state: 'absent', text: '—' }
}

/**
 * A batch's timestamp, in the viewer's timezone.
 *
 * The backend stores the instant and sends it as ISO 8601 with an offset; the
 * label is formatted here rather than server-side because the server runs in
 * UTC and a timestamp baked into the label would show the wrong local time to
 * whoever is reading it.
 */
export function batchLabel(batch) {
  const when = new Date(batch.created_at)
  return `${batch.label} — ${when.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })}`
}
