import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { triggerAgentAnalysis } from '../api'

const COUNTRY = { FR:'France', DE:'Germany', ES:'Spain', IT:'Italy', NL:'Netherlands', PL:'Poland', IE:'Ireland' }

function fmt(n, dec = 0) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

// ── Risk score badge ──────────────────────────────────────────────────────────

const RISK = {
  red:   { bg: '#fde8e8', color: '#c0392b', border: '#f5c6cb', label: '● RED',   title: 'Both risk factories flagged' },
  amber: { bg: '#fff3cd', color: '#856404', border: '#ffc107', label: '● AMBER', title: 'One risk factory flagged' },
  green: { bg: '#d4edda', color: '#155724', border: '#c3e6cb', label: '● GREEN', title: 'No risk signals' },
}

function RiskBadge({ score }) {
  const r = RISK[score] || RISK.green
  return (
    <span title={r.title} style={{
      background: r.bg, color: r.color,
      border: `1px solid ${r.border}`,
      padding: '2px 9px', borderRadius: 10,
      fontSize: 11, fontWeight: 700,
    }}>
      {r.label}
    </span>
  )
}

// ── Analyse button (DISABLED) ─────────────────────────────────────────────────
//
// The VAT Fraud Detection Agent is now driven exclusively from the
// revenue-guardian UI on http://localhost:8080. Investigations land in the
// holding queue (POST /api/investigations/* endpoints) and the operator
// triggers the agent + decides release/retain from there. The button below
// is kept as a non-interactive chip so the column layout doesn't shift.

function AnalyseButton(_props) {
  return (
    <span
      title="Agent control has moved to the Revenue Guardian UI on :8080"
      style={{
        fontSize: 11,
        color: 'var(--text-muted)',
        background: '#f1f3f5',
        border: '1px dashed var(--border)',
        borderRadius: 'var(--radius)',
        padding: '3px 8px',
        fontWeight: 600,
        whiteSpace: 'nowrap',
        cursor: 'help',
      }}>
      ⚡ Agent in Revenue Guardian
    </span>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SuspiciousPage() {
  const [items,   setItems]   = useState([])
  const [alarms,  setAlarms]  = useState([])
  const [loading, setLoading] = useState(false)
  const [queued,  setQueued]  = useState(new Set())

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [txRes, alRes] = await Promise.all([
        axios.get('/api/suspicious?limit=50'),
        axios.get('/api/alarms?active_only=false'),
      ])
      setItems(txRes.data)
      setAlarms(alRes.data)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh])

  const activeAlarms = alarms.filter(a => a.active)

  return (
    <div className="page-container">
      <div className="page-title">Suspicious Transactions</div>
      <div className="page-subtitle">
        Transactions flagged by RT Risk Monitoring — use ⚡ Analyse to trigger AI investigation
      </div>

      {/* Active alarm summary cards */}
      {activeAlarms.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--error)', marginBottom: 10 }}>
            ⚠ {activeAlarms.length} active alarm{activeAlarms.length > 1 ? 's' : ''}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px,1fr))', gap: 12 }}>
            {activeAlarms.map(a => <AlarmCard key={a.id} alarm={a} />)}
          </div>
        </div>
      )}

      {/* Legend */}
      <div style={{
        display: 'flex', gap: 16, alignItems: 'center',
        marginBottom: 12, fontSize: 11, color: 'var(--text-secondary)',
      }}>
        <span style={{ fontWeight: 700 }}>Risk score:</span>
        {Object.entries(RISK).map(([k, r]) => (
          <span key={k} style={{
            background: r.bg, color: r.color, border: `1px solid ${r.border}`,
            padding: '2px 9px', borderRadius: 10, fontWeight: 700,
          }}>{r.label}</span>
        ))}
        <span style={{ marginLeft: 8 }}>
          RED = both factories flagged · AMBER = one factory · GREEN = none
        </span>
      </div>

      {/* Suspicious transaction table */}
      <div className="card">
        <div className="card-header">
          <span>Flagged Transactions</span>
          {loading && <span className="text-muted" style={{ fontSize: 11 }}>Refreshing…</span>}
        </div>
        {items.length === 0 ? (
          <div className="alarms-empty">
            <div className="alarms-empty__icon">🔍</div>
            <div className="alarms-empty__text">
              No suspicious transactions yet.
              <br />
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                Scenario: TechZone GmbH → IE triggers in week 2 of March (8–14 Mar 2026).
              </span>
            </div>
          </div>
        ) : (
          <div className="tx-table-wrap">
            <table className="tx-table">
              <thead>
                <tr>
                  <th>Date / Time</th>
                  <th>Seller</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Item</th>
                  <th style={{ textAlign: 'right' }}>Value (€)</th>
                  <th style={{ textAlign: 'right' }}>Applied VAT</th>
                  <th style={{ textAlign: 'right' }}>Correct VAT</th>
                  <th style={{ textAlign: 'right' }}>Deviation</th>
                  <th style={{ textAlign: 'center' }}>Risk</th>
                  <th style={{ textAlign: 'center' }}>AI Agent</th>
                </tr>
              </thead>
              <tbody>
                {items.map(r => {
                  const riskLevel = r.suspicion_level || 'amber'
                  const rowBg = riskLevel === 'red'   ? '#fff5f5'
                               : riskLevel === 'high' ? '#fff5f5'
                               : '#fffdf0'
                  return (
                    <tr key={r.transaction_id} style={{ background: rowBg }}>
                      <td>{r.transaction_date?.slice(0, 16).replace('T', ' ')}</td>
                      <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        <span style={{ color: 'var(--error)', fontWeight: 700, marginRight: 4 }}>⚠</span>
                        {r.seller_name}
                      </td>
                      <td><span className="badge country">{r.seller_country}</span></td>
                      <td><span className="badge country">{r.buyer_country}</span></td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {r.item_description}
                      </td>
                      <td style={{ textAlign: 'right' }}>{fmt(r.value, 2)}</td>
                      <td style={{ textAlign: 'right', color: r.has_error ? 'var(--error)' : 'inherit', fontWeight: 700 }}>
                        {(r.vat_rate * 100).toFixed(1)}%
                      </td>
                      <td style={{ textAlign: 'right', color: 'var(--success)' }}>
                        {(r.correct_vat_rate * 100).toFixed(1)}%
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {r.deviation_pct != null
                          ? <span style={{ background: '#fde8e8', color: 'var(--error)', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700 }}>
                              +{fmt(r.deviation_pct, 1)}%
                            </span>
                          : <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>watchlist</span>
                        }
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <RiskBadge score={
                          r.suspicion_level === 'high' ? 'red'
                          : r.suspicion_level === 'red' ? 'red'
                          : r.suspicion_level === 'amber' ? 'amber'
                          : 'amber'
                        } />
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        {queued.has(r.transaction_id)
                          ? <span style={{ fontSize: 11, color: 'var(--success)', fontWeight: 700 }}>⚙ Queued</span>
                          : <AnalyseButton txId={r.transaction_id}
                              onQueued={id => setQueued(prev => new Set([...prev, id]))} />
                        }
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Alarm history */}
      {alarms.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-header">Alarm History (RT Risk Monitoring 1)</div>
          <div className="tx-table-wrap">
            <table className="tx-table">
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th>Buyer country</th>
                  <th>Raised at</th>
                  <th>Expires at</th>
                  <th style={{ textAlign: 'right' }}>Current ratio</th>
                  <th style={{ textAlign: 'right' }}>Historical ratio</th>
                  <th style={{ textAlign: 'right' }}>Deviation</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {alarms.map(a => (
                  <tr key={a.id}>
                    <td style={{ fontWeight: 700 }}>{a.supplier_name}</td>
                    <td><span className="badge country">{a.buyer_country}</span> {COUNTRY[a.buyer_country]}</td>
                    <td>{a.raised_at?.slice(0, 16).replace('T', ' ')}</td>
                    <td>{a.expires_at?.slice(0, 10)}</td>
                    <td style={{ textAlign: 'right', color: 'var(--error)', fontWeight: 700 }}>
                      {fmt(a.ratio_current * 100, 2)}%
                    </td>
                    <td style={{ textAlign: 'right', color: 'var(--success)' }}>
                      {fmt(a.ratio_historical * 100, 2)}%
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <span style={{ background: '#fde8e8', color: 'var(--error)', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700 }}>
                        +{fmt(a.deviation_pct, 1)}%
                      </span>
                    </td>
                    <td>
                      {a.active
                        ? <span className="badge err">Active</span>
                        : <span className="badge ok">Expired</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function AlarmCard({ alarm }) {
  const country = COUNTRY[alarm.buyer_country] || alarm.buyer_country
  return (
    <div style={{
      background: '#fff8f8', border: '1px solid #f5c6cb',
      borderLeft: '4px solid var(--error)',
      borderRadius: 'var(--radius)', padding: '14px 16px',
      boxShadow: 'var(--shadow)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--error)' }}>⚠ {alarm.supplier_name}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>→ {country} ({alarm.buyer_country})</div>
        </div>
        <span className="badge err">Active</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 10 }}>
        <Stat label="Current ratio"  value={`${(alarm.ratio_current * 100).toFixed(2)}%`}  color="var(--error)" />
        <Stat label="Historical avg" value={`${(alarm.ratio_historical * 100).toFixed(2)}%`} color="var(--success)" />
        <Stat label="Deviation"      value={`+${alarm.deviation_pct.toFixed(1)}%`}           color="var(--error)" />
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
        Raised: {alarm.raised_at?.slice(0,16).replace('T',' ')} · Expires: {alarm.expires_at?.slice(0,10)}
      </div>
    </div>
  )
}

function Stat({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}
