import { useState, useEffect, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, PieChart, Pie, Cell, Legend,
} from 'recharts'
import { getMetrics, getSuppliers, getCountries } from '../api'

const EU_BLUE    = '#003399'
const EU_YELLOW  = '#FFED00'
const PALETTE    = ['#003399','#0050a0','#0070b8','#009bde','#00bcd4','#4caf7c','#f4a021','#d62728']
const COUNTRY    = { FR:'France', DE:'Germany', ES:'Spain', IT:'Italy', NL:'Netherlands', PL:'Poland' }

function fmt(n, dec = 0) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

function fmtPct(v, total) {
  if (!total) return ''
  return ` (${(v / total * 100).toFixed(1)}%)`
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background:'#fff', border:'1px solid #ddd', borderRadius:2, padding:'8px 12px', fontSize:12 }}>
      <div style={{ fontWeight:700, marginBottom:4 }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color }}>
          {p.name}: <strong>€{fmt(p.value, 2)}</strong>
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [suppliers, setSuppliers]   = useState([])
  const [countries, setCountries]   = useState([])
  const [filters, setFilters]       = useState({ seller_name:'', buyer_country:'', seller_country:'', date_from:'', date_to:'' })
  const [applied, setApplied]       = useState({})
  const [metrics, setMetrics]       = useState(null)
  const [loading, setLoading]       = useState(false)

  useEffect(() => {
    getSuppliers().then(setSuppliers).catch(() => {})
    getCountries().then(setCountries).catch(() => {})
  }, [])

  const fetchMetrics = useCallback(async (params) => {
    setLoading(true)
    try { setMetrics(await getMetrics(params)) } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { fetchMetrics(applied) }, [applied, fetchMetrics])

  const applyFilters = () => setApplied({ ...filters })

  const set = (k, v) => setFilters(f => ({ ...f, [k]: v }))

  // ── Charts data ───────────────────────────────────────────────────────────
  const byBuyer    = (metrics?.by_buyer_country || []).map(r => ({
    name: COUNTRY[r.buyer_country] || r.buyer_country,
    vat: r.vat, n: r.n,
  }))
  const bySeller   = (metrics?.by_seller || []).slice(0, 8).map(r => ({
    name: r.seller_name, vat: r.vat, n: r.n,
  }))
  const daily      = (metrics?.daily_vat || []).map(r => ({ date: r.day?.slice(5), vat: r.vat }))
  const byCategory = (metrics?.by_category || []).map(r => ({
    name: r.item_category?.replace(/_/g, ' '), value: r.vat,
  }))
  const total = metrics?.total_vat || 0

  return (
    <div className="page-container">
      <div className="page-title">Dashboard</div>
      <div className="page-subtitle">VAT compliance metrics · European Custom Database</div>

      {/* Filters */}
      <div className="filter-bar">
        <div className="filter-group">
          <label>Supplier</label>
          <select value={filters.seller_name} onChange={e => set('seller_name', e.target.value)}>
            <option value="">All suppliers</option>
            {suppliers.map(s => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Buyer country</label>
          <select value={filters.buyer_country} onChange={e => set('buyer_country', e.target.value)}>
            <option value="">All countries</option>
            {countries.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Seller country</label>
          <select value={filters.seller_country} onChange={e => set('seller_country', e.target.value)}>
            <option value="">All countries</option>
            {countries.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>From</label>
          <input type="date" value={filters.date_from} onChange={e => set('date_from', e.target.value)} />
        </div>
        <div className="filter-group">
          <label>To</label>
          <input type="date" value={filters.date_to} onChange={e => set('date_to', e.target.value)} />
        </div>
        <button className="filter-apply" onClick={applyFilters}>Apply</button>
      </div>

      {/* KPI row */}
      {metrics && (
        <div className="metrics-row" style={{ marginBottom: 20 }}>
          <div className="metric-tile">
            <div className="metric-tile__label">Transactions</div>
            <div className="metric-tile__value">{fmt(metrics.total_transactions)}</div>
          </div>
          <div className="metric-tile accent">
            <div className="metric-tile__label">Total value (€)</div>
            <div className="metric-tile__value">{fmt(metrics.total_value, 0)}</div>
          </div>
          <div className="metric-tile">
            <div className="metric-tile__label">VAT due (€)</div>
            <div className="metric-tile__value">{fmt(metrics.total_vat, 0)}</div>
          </div>
          <div className={`metric-tile ${metrics.error_count > 0 ? 'error-tile' : ''}`}>
            <div className="metric-tile__label">Rate errors</div>
            <div className="metric-tile__value">{fmt(metrics.error_count)}</div>
            <div className="metric-tile__sub">
              {metrics.total_transactions
                ? `${(metrics.error_count / metrics.total_transactions * 100).toFixed(1)}% of total`
                : ''}
            </div>
          </div>
        </div>
      )}

      {loading && <div className="text-muted" style={{ marginBottom:12 }}>Refreshing…</div>}

      {/* Row 1: VAT by buyer country + daily trend */}
      <div className="two-col section-gap">
        <div className="card">
          <div className="card-header">VAT due by buyer country</div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={byBuyer} margin={{ top:4, right:8, left:0, bottom:4 }}>
                <XAxis dataKey="name" tick={{ fontSize:11 }} />
                <YAxis tick={{ fontSize:11 }} tickFormatter={v => `€${(v/1000).toFixed(0)}k`} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="vat" name="VAT due" fill={EU_BLUE} radius={[2,2,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="card-header">Daily VAT due</div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={daily} margin={{ top:4, right:8, left:0, bottom:4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                <XAxis dataKey="date" tick={{ fontSize:10 }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize:11 }} tickFormatter={v => `€${(v/1000).toFixed(0)}k`} />
                <Tooltip content={<CustomTooltip />} />
                <Line type="monotone" dataKey="vat" name="VAT due" stroke={EU_BLUE} dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Row 2: VAT by supplier + category pie */}
      <div className="two-col section-gap">
        <div className="card">
          <div className="card-header">VAT due by supplier</div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart layout="vertical" data={bySeller} margin={{ top:4, right:40, left:0, bottom:4 }}>
                <XAxis type="number" tick={{ fontSize:11 }} tickFormatter={v => `€${(v/1000).toFixed(0)}k`} />
                <YAxis type="category" dataKey="name" width={160} tick={{ fontSize:10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="vat" name="VAT due" fill={EU_BLUE} radius={[0,2,2,0]}>
                  {bySeller.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="card-header">VAT due by product category</div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={byCategory} dataKey="value" nameKey="name"
                     cx="50%" cy="50%" outerRadius={90}
                     label={({ name, value }) => `${name}: €${fmt(value, 0)}`}
                     labelLine={false}>
                  {byCategory.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                </Pie>
                <Legend iconSize={10} iconType="circle"
                        formatter={(v) => <span style={{ fontSize: 11 }}>{v}</span>} />
                <Tooltip formatter={(v) => `€${fmt(v, 2)}`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Error breakdown */}
      {metrics && metrics.error_count > 0 && (
        <div className="card section-gap">
          <div className="card-header" style={{ color: 'var(--error)' }}>
            ⚠ VAT Rate Errors — {fmt(metrics.error_count)} transactions
            <span style={{ fontWeight:400, fontSize:12, color:'var(--text-muted)' }}>
              Applied rate differs from the OSS destination-country rate
            </span>
          </div>
          <div className="card-body">
            <p style={{ fontSize:13, color:'var(--text-secondary)', lineHeight:1.6 }}>
              Under the EU OSS rules (effective July 2021), B2C cross-border e-commerce
              must apply the <strong>VAT rate of the buyer's country</strong>.
              Errors shown here indicate the supplier applied their own country's rate instead.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
