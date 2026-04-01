import { useState, useEffect, useRef, useCallback } from 'react'
import { getQueue, getMetrics } from '../api'

const COUNTRY = { FR:'France', DE:'Germany', ES:'Spain', IT:'Italy', NL:'Netherlands', PL:'Poland' }

// ── Period presets ────────────────────────────────────────────────────────────
const PERIODS = [
  { label: 'Last 7 days',  days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 3 months',days: 91 },
  { label: 'All time',     days: null },
  { label: 'Custom',       days: -1 },
]

function toDateStr(daysAgo) {
  if (daysAgo == null) return null
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return d.toISOString().slice(0, 10)
}

function fmt(n, dec = 0) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

// ── Metrics row ───────────────────────────────────────────────────────────────
function MetricsRow({ metrics, loading }) {
  if (loading && !metrics) return <div className="metrics-row"><div className="metric-tile" style={{gridColumn:'span 4'}}>Loading…</div></div>
  if (!metrics) return null
  const { total_transactions, total_value, total_vat, error_count } = metrics
  const errorPct = total_transactions ? (error_count / total_transactions * 100) : 0
  return (
    <div className="metrics-row">
      <div className="metric-tile">
        <div className="metric-tile__label">Total transactions</div>
        <div className="metric-tile__value">{fmt(total_transactions)}</div>
        <div className="metric-tile__sub">in selected period</div>
      </div>
      <div className="metric-tile accent">
        <div className="metric-tile__label">Total value (€)</div>
        <div className="metric-tile__value">{fmt(total_value, 0)}</div>
        <div className="metric-tile__sub">gross transaction value</div>
      </div>
      <div className="metric-tile">
        <div className="metric-tile__label">VAT due (€)</div>
        <div className="metric-tile__value">{fmt(total_vat, 0)}</div>
        <div className="metric-tile__sub">based on applied rate × value</div>
      </div>
      <div className={`metric-tile ${error_count > 0 ? 'error-tile' : ''}`}>
        <div className="metric-tile__label">Rate errors</div>
        <div className="metric-tile__value">{fmt(error_count)}</div>
        <div className="metric-tile__sub">{errorPct.toFixed(1)}% of transactions</div>
      </div>
    </div>
  )
}

// ── Transaction table ─────────────────────────────────────────────────────────
function TxTable({ items, prevIds }) {
  if (!items?.length) return (
    <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
      No transactions yet — start the simulation using the ▶ button in the header.
    </div>
  )
  return (
    <div className="tx-table-wrap">
      <table className="tx-table">
        <thead>
          <tr>
            <th>Date / Time</th>
            <th>Seller</th>
            <th>From</th>
            <th>To</th>
            <th>Item</th>
            <th>Category</th>
            <th style={{textAlign:'right'}}>Value (€)</th>
            <th style={{textAlign:'right'}}>VAT rate</th>
            <th style={{textAlign:'right'}}>VAT due (€)</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map(r => {
            const isNew = !prevIds.current.has(r.transaction_id)
            return (
              <tr key={r.transaction_id} className={isNew ? 'new-row' : ''}>
                <td>{r.transaction_date?.slice(0, 16).replace('T', ' ')}</td>
                <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.seller_name}</td>
                <td><span className="badge country">{r.seller_country}</span></td>
                <td><span className="badge country">{r.buyer_country}</span></td>
                <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.item_description}</td>
                <td style={{ color: 'var(--text-secondary)' }}>{r.item_category?.replace('_', ' ')}</td>
                <td style={{ textAlign: 'right' }}>{fmt(r.value, 2)}</td>
                <td style={{ textAlign: 'right' }}>{(r.vat_rate * 100).toFixed(1)}%</td>
                <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(r.vat_amount, 2)}</td>
                <td>
                  {r.has_error
                    ? <span className="badge err" title={`Correct rate: ${(r.correct_vat_rate*100).toFixed(1)}%`}>⚠ Error</span>
                    : <span className="badge ok">✓ OK</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Alarms panel ──────────────────────────────────────────────────────────────
function AlarmsPanel() {
  return (
    <div className="card section-gap">
      <div className="card-header">
        🔔 Alarms
        <span className="text-muted" style={{ fontWeight: 400 }}>0 active</span>
      </div>
      <div className="alarms-empty">
        <div className="alarms-empty__icon">🔕</div>
        <div className="alarms-empty__text">No alarms at this time. Alarm rules will be configurable in a future release.</div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function MainPage() {
  const [periodIdx, setPeriodIdx]   = useState(1)          // default: last 30 days
  const [customFrom, setCustomFrom] = useState('')
  const [customTo,   setCustomTo]   = useState('')
  const [metrics, setMetrics]       = useState(null)
  const [metricsLoading, setML]     = useState(false)
  const [queue, setQueue]           = useState([])
  const prevIds = useRef(new Set())

  const isCustom = PERIODS[periodIdx].days === -1

  const dateFrom = isCustom
    ? (customFrom || null)
    : toDateStr(PERIODS[periodIdx].days)

  const dateTo = isCustom ? (customTo || null) : null

  // Fetch metrics
  const fetchMetrics = useCallback(async () => {
    setML(true)
    try {
      const m = await getMetrics({ date_from: dateFrom, date_to: dateTo })
      setMetrics(m)
    } catch { /* ignore */ }
    setML(false)
  }, [dateFrom, dateTo])

  // Fetch live queue (polls every 2s)
  const fetchQueue = useCallback(async () => {
    try {
      const data = await getQueue()
      const items = data.items || []
      const newIds = new Set(items.map(r => r.transaction_id))
      prevIds.current = newIds
      setQueue(items)
    } catch { /* ignore */ }
  }, [])

  // Initial + periodic metrics refresh
  useEffect(() => { fetchMetrics() }, [fetchMetrics])
  useEffect(() => {
    const id = setInterval(fetchMetrics, 10000)   // every 10s
    return () => clearInterval(id)
  }, [fetchMetrics])

  // Live queue — every 2s
  useEffect(() => {
    fetchQueue()
    const id = setInterval(fetchQueue, 2000)
    return () => clearInterval(id)
  }, [fetchQueue])

  // Track new rows for flash animation
  const trackedIds = useRef(new Set())
  useEffect(() => {
    queue.forEach(r => trackedIds.current.add(r.transaction_id))
  }, [queue])

  return (
    <div className="page-container">
      <div className="page-title">Main</div>
      <div className="page-subtitle">
        European Custom Database — real-time B2C e-commerce transaction monitoring
      </div>

      {/* Period selector */}
      <div className="period-bar">
        <label>Period:</label>
        {PERIODS.map((p, i) => (
          <button key={p.label}
                  className={`period-btn ${periodIdx === i ? 'active' : ''}`}
                  onClick={() => setPeriodIdx(i)}>
            {p.label}
          </button>
        ))}
        {isCustom && (
          <div className="period-custom">
            <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} />
            <span style={{ color: 'var(--text-muted)' }}>→</span>
            <input type="date" value={customTo}   onChange={e => setCustomTo(e.target.value)} />
          </div>
        )}
      </div>

      {/* KPI tiles */}
      <MetricsRow metrics={metrics} loading={metricsLoading} />

      {/* Live queue */}
      <div className="card section-gap">
        <div className="card-header">
          <span><span className="live-dot" />Live Transaction Queue — last 30</span>
          <span className="text-muted" style={{ fontSize: 11 }}>auto-refresh every 2 s</span>
        </div>
        <TxTable items={queue} prevIds={trackedIds} />
      </div>

      {/* Alarms */}
      <AlarmsPanel />
    </div>
  )
}
