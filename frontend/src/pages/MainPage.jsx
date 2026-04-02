import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getQueue, getMetrics } from '../api'
const QUEUE_SIZE = 30
import axios from 'axios'

const COUNTRY = { FR:'France', DE:'Germany', ES:'Spain', IT:'Italy', NL:'Netherlands', PL:'Poland', IE:'Ireland' }

// ── Period presets ────────────────────────────────────────────────────────────
const PERIODS = [
  { label: 'Last 7 days',  days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 3 months',days: 91 },
  { label: 'All time',     days: null },
  { label: 'Custom',       days: -1 },
]

// Uses simulation time as "today" so period selectors are relative to the
// simulated date, not the browser's real date.  Falls back to real date.
function toDateStr(daysAgo, simTime) {
  if (daysAgo == null) return null
  const base = simTime ? new Date(simTime) : new Date()
  base.setDate(base.getDate() - daysAgo)
  return base.toISOString().slice(0, 10)
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
  const [alarms, setAlarms] = useState([])
  const navigate = useNavigate()

  useEffect(() => {
    const fetch = () => axios.get('/api/alarms?active_only=true')
      .then(r => setAlarms(r.data)).catch(() => {})
    fetch()
    const id = setInterval(fetch, 5000)
    return () => clearInterval(id)
  }, [])

  const active = alarms.filter(a => a.active)

  return (
    <div className="card section-gap">
      <div className="card-header">
        🔔 Alarms
        <span style={{
          background: active.length ? '#fde8e8' : '#d4edda',
          color: active.length ? 'var(--error)' : 'var(--success)',
          padding: '2px 10px', borderRadius: 10, fontSize: 12, fontWeight: 700,
        }}>
          {active.length} active
        </span>
      </div>

      {active.length === 0 ? (
        <div className="alarms-empty">
          <div className="alarms-empty__icon">🔕</div>
          <div className="alarms-empty__text">
            No active alarms. VAT ratio deviation alarms will appear here when triggered.
            <br />
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              Scenario: TechZone GmbH → IE alarm fires during week 2 of March 2026.
            </span>
          </div>
        </div>
      ) : (
        <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {active.map(a => (
            <div key={a.id} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 14px',
              background: '#fff8f8',
              border: '1px solid #f5c6cb',
              borderLeft: '4px solid var(--error)',
              borderRadius: 'var(--radius)',
              gap: 16,
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, color: 'var(--error)', fontSize: 13 }}>
                  ⚠ {a.supplier_name} → {COUNTRY[a.buyer_country] || a.buyer_country}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 3 }}>
                  VAT/value ratio: <strong style={{ color: 'var(--error)' }}>{(a.ratio_current * 100).toFixed(2)}%</strong>
                  {' vs historical '}
                  <strong style={{ color: 'var(--success)' }}>{(a.ratio_historical * 100).toFixed(2)}%</strong>
                  {' · deviation: '}
                  <strong>+{a.deviation_pct.toFixed(1)}%</strong>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                  Raised: {a.raised_at?.slice(0,16).replace('T',' ')} · Expires: {a.expires_at?.slice(0,10)}
                </div>
              </div>
              <button
                onClick={() => navigate('/suspicious')}
                style={{
                  background: 'var(--error)', color: '#fff', border: 'none',
                  borderRadius: 'var(--radius)', padding: '5px 14px',
                  fontSize: 12, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >
                View suspicious →
              </button>
            </div>
          ))}
        </div>
      )}
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
  const [simTime, setSimTime]       = useState(null)        // current simulation date
  // Poll simulation time so period selectors are relative to the sim clock
  useEffect(() => {
    const fetch = () => axios.get('/api/simulation/status')
      .then(r => setSimTime(r.data.sim_time)).catch(() => {})
    fetch()
    const id = setInterval(fetch, 5000)
    return () => clearInterval(id)
  }, [])

  const isCustom = PERIODS[periodIdx].days === -1

  const dateFrom = isCustom
    ? (customFrom || null)
    : toDateStr(PERIODS[periodIdx].days, simTime)

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

  // Initial + periodic metrics refresh
  useEffect(() => { fetchMetrics() }, [fetchMetrics])
  useEffect(() => {
    const id = setInterval(fetchMetrics, 10000)   // every 10s
    return () => clearInterval(id)
  }, [fetchMetrics])

  // Live queue — SSE for one-by-one delivery, fallback snapshot on connect
  const trackedIds = useRef(new Set())
  useEffect(() => {
    let es = null
    let cancelled = false

    // Load initial snapshot from REST endpoint
    getQueue().then(data => {
      if (cancelled) return
      const items = (data.items || []).slice(0, QUEUE_SIZE)
      items.forEach(r => trackedIds.current.add(r.transaction_id))
      setQueue(items)
    }).catch(() => {})

    // Open SSE stream for subsequent live updates
    es = new EventSource('/api/queue/stream')

    es.onmessage = (evt) => {
      if (cancelled) return
      if (evt.data === '__reset__') {
        trackedIds.current = new Set()
        setQueue([])
        return
      }
      try {
        const row = JSON.parse(evt.data)
        setQueue(prev => {
          if (trackedIds.current.has(row.transaction_id)) return prev
          trackedIds.current.add(row.transaction_id)
          const next = [row, ...prev].slice(0, QUEUE_SIZE)
          return next
        })
      } catch { /* ignore parse errors */ }
    }

    es.onerror = () => { /* browser auto-reconnects */ }

    return () => {
      cancelled = true
      es?.close()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
          <span className="text-muted" style={{ fontSize: 11 }}>live stream</span>
        </div>
        <TxTable items={queue} prevIds={trackedIds} />
      </div>

      {/* Alarms */}
      <AlarmsPanel />
    </div>
  )
}
