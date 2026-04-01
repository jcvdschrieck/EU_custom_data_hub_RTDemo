import axios from 'axios'

const http = axios.create({ baseURL: '' })

// ── Queue & simulation ────────────────────────────────────────────────────────
export const getQueue       = ()       => http.get('/api/queue').then(r => r.data)
export const getSimStatus   = ()       => http.get('/api/simulation/status').then(r => r.data)
export const simStart       = ()       => http.post('/api/simulation/start').then(r => r.data)
export const simPause       = ()       => http.post('/api/simulation/pause').then(r => r.data)
export const simResume      = ()       => http.post('/api/simulation/resume').then(r => r.data)
export const simReset       = ()       => http.post('/api/simulation/reset').then(r => r.data)
export const simSetSpeed    = (speed)  => http.post('/api/simulation/speed', { speed }).then(r => r.data)

// ── Metrics & data ────────────────────────────────────────────────────────────
export const getMetrics = (params) =>
  http.get('/api/metrics', { params: clean(params) }).then(r => r.data)

export const getTransactions = (params) =>
  http.get('/api/transactions', { params: clean(params) }).then(r => r.data)

// ── Catalog ───────────────────────────────────────────────────────────────────
export const getSuppliers  = () => http.get('/api/catalog/suppliers').then(r => r.data)
export const getCountries  = () => http.get('/api/catalog/countries').then(r => r.data)

function clean(obj) {
  if (!obj) return {}
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v != null && v !== ''))
}
