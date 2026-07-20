/**
 * Wrapper around fetch() that parses JSON responses and handles errors
 * @param {string} url - URL to fetch
 * @param {object} options - fetch options
 * @returns {Promise<any>} parsed JSON
 */
export async function fetchJson(url, options = {}) {
  const res = await fetch(url, options)
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }
  return res.json()
}
