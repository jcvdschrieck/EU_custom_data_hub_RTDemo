import { useState, useEffect, useCallback } from 'react'
import { getMetrics } from '../api'
import axios from 'axios'

const COUNTRY = { FR:'France', DE:'Germany', ES:'Spain', IT:'Italy', NL:'Netherlands', PL:'Poland' }

function fmt(n, dec = 0) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

export default function SuspiciousPage() {
  const [items, setItems]   = useState([])
  const [alarms, setAlarms] = useState([])
  const [loading, setLoading] = useState(false)

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
        Transactions flagged while a VAT ratio deviation alarm is active — last 50
      </div>

      {/* Active alarm summary cards */}
      {activeAlarms.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--error)', marginBottom: 10 }}>
            ⚠ {activeAlarms.length} active alarm{activeAlarms.length > 1 ? 's' : ''}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px,1fr))', gap: 12 }}>
            {activeAlarms.map(a => (
              <AlarmCard key={a.id} alarm={a} />
            ))}
          </div>
        </div>
      )}

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
              No suspicious transactions yet. Alarms will be raised when a supplier's
              VAT/value ratio deviates &gt;25% from its 8-week baseline.
              <br />
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                Scenario: GourmetShop Lyon → PL triggers in week 2 of March (8–14 Mar 2026).
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
                  <th style={{ textAlign: 'right' }}>VAT Due (€)</th>
                  <th style={{ textAlign: 'right' }}>Deviation</th>
                  <th>Alarm expires</th>
                </tr>
              </thead>
              <tbody>
                {items.map(r => (
                  <tr key={r.transaction_id} style={{ background: '#fff8f8' }}>
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
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(r.vat_amount, 2)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <span style={{
                        background: '#fde8e8', color: 'var(--error)',
                        padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700,
                      }}>
                        +{fmt(r.deviation_pct, 1)}%
                      </span>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {r.alarm_expires_at?.slice(0, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* All alarms history */}
      {alarms.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-header">Alarm History</div>
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
                      <span style={{
                        background: '#fde8e8', color: 'var(--error)',
                        padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700,
                      }}>
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
  const raised  = alarm.raised_at?.slice(0, 16).replace('T', ' ')
  const expires = alarm.expires_at?.slice(0, 10)

  return (
    <div style={{
      background: '#fff8f8',
      border: '1px solid #f5c6cb',
      borderLeft: '4px solid var(--error)',
      borderRadius: 'var(--radius)',
      padding: '14px 16px',
      boxShadow: 'var(--shadow)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--error)' }}>⚠ {alarm.supplier_name}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
            → {country} ({alarm.buyer_country})
          </div>
        </div>
        <span className="badge err">Active</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 10 }}>
        <Stat label="Current ratio" value={`${(alarm.ratio_current * 100).toFixed(2)}%`} color="var(--error)" />
        <Stat label="Historical avg" value={`${(alarm.ratio_historical * 100).toFixed(2)}%`} color="var(--success)" />
        <Stat label="Deviation" value={`+${alarm.deviation_pct.toFixed(1)}%`} color="var(--error)" />
      </div>

      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
        Raised: {raised} · Expires: {expires}
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
