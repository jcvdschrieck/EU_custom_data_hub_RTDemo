import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'

const VERDICT = {
  incorrect:    { icon: '❌', color: 'var(--error)',   bg: '#fff0f0', label: 'INCORRECT'    },
  suspicious:   { icon: '🔴', color: 'var(--error)',   bg: '#fff0f0', label: 'SUSPICIOUS'   },
  correct:      { icon: '✅', color: 'var(--success)', bg: '#f0fff4', label: 'CORRECT'      },
  legitimate:   { icon: '✅', color: 'var(--success)', bg: '#f0fff4', label: 'LEGITIMATE'   },
  uncertain:    { icon: '❓', color: '#856404',        bg: '#fffbe6', label: 'UNCERTAIN'    },
  processing:   { icon: '⚙️', color: '#005ea2',        bg: '#e8f1f8', label: 'PROCESSING'   },
  queued:       { icon: '📥', color: '#666',           bg: '#f5f5f5', label: 'QUEUED'       },
  case_created: { icon: '📋', color: '#2e7d32',        bg: '#f0fff4', label: 'CASE CREATED' },
  sent_to_tax:  { icon: '📤', color: '#005ea2',        bg: '#e8f1f8', label: 'SENT TO TAX'  },
}

function fmt(n, dec = 2) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

const DARK_TEXT = '#1a1a2e'

function LogLine({ entry, onDetails }) {
  const v = VERDICT[entry.verdict] || VERDICT.uncertain
  const isLifecycle = ['queued', 'processing', 'case_created', 'sent_to_tax'].includes(entry.verdict)
  const ts = (entry.processed_at || '').slice(11, 19)

  const caseLabel = (entry.transaction_id || '').startsWith('CASE-')
    ? 'Case ' + (entry.transaction_id || '').slice(5, 17)
    : 'Tx ' + (entry.transaction_id || '').slice(-8).toUpperCase()

  const reason = entry.reasoning ? (' — ' + (entry.reasoning || '').slice(0, 80)) : ''

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '7px 14px',
      borderBottom: '1px solid rgba(0,0,0,0.05)',
      background: v.bg,
      fontFamily: '"Courier New", Courier, monospace',
    }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap',
                     minWidth: 60, paddingTop: 1 }}>
        {ts || '—'}
      </span>
      <span style={{ fontSize: 14, minWidth: 20, paddingTop: 1 }}>{v.icon}</span>
      <span style={{ fontSize: 11.5, color: DARK_TEXT, flex: 1, lineHeight: 1.5 }}>
        <span style={{ color: v.color, fontWeight: 700 }}>[{v.label}] </span>
        {caseLabel}{entry.seller_name ? (' · ' + entry.seller_name) : ''}{reason}
      </span>
      {!isLifecycle && (
        <button onClick={() => onDetails(entry)} style={{
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
          fontSize: 10, color: 'var(--primary)', whiteSpace: 'nowrap',
        }}>
          Details ↗
        </button>
      )}
    </div>
  )
}

function DetailDrawer({ entry, onClose }) {
  if (!entry) return null
  const v = VERDICT[entry.verdict] || VERDICT.uncertain
  return (
    <>
      <div onClick={onClose} style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 900,
      }} />
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 480,
        background: '#fff', zIndex: 901,
        boxShadow: '-4px 0 24px rgba(0,0,0,0.18)',
        display: 'flex', flexDirection: 'column',
        overflowY: 'auto', padding: 20,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, color: v.color }}>{v.icon} {v.label}</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{entry.transaction_id}</div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: '1px solid var(--border)',
            borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 16,
          }}>✕</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 12, marginBottom: 16 }}>
          {[
            ['Seller', entry.seller_name],
            ['Destination', entry.buyer_country],
            ['Product', entry.item_description],
            ['Category', entry.item_category],
            ['Value', entry.value != null ? '€ ' + fmt(entry.value) : '—'],
            ['VAT Rate', entry.vat_rate != null ? (entry.vat_rate * 100).toFixed(1) + '%' : '—'],
            ['Processed', (entry.processed_at || '').slice(0, 19).replace('T', ' ')],
          ].map(([k, val]) => (
            <div key={k}><span style={{ color: 'var(--text-muted)' }}>{k}: </span><strong>{val || '—'}</strong></div>
          ))}
        </div>
        <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 8 }}>
          Agent Reasoning
        </div>
        <div style={{
          background: '#f8f9fa', border: '1px solid var(--border)',
          borderRadius: 6, padding: '10px 12px', fontSize: 12, lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
        }}>
          {entry.reasoning || '—'}
        </div>
      </div>
    </>
  )
}

export default function ProcessingLogPage() {
  const [log, setLog] = useState([])
  const [detail, setDetail] = useState(null)
  const [stats, setStats] = useState({ total: 0, suspicious: 0, cleared: 0, uncertain: 0, queued: 0, processing: 0 })
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const res = await axios.get('/api/agent-log?limit=500')
      const data = Array.isArray(res.data) ? res.data : []
      setLog([...data].reverse())
      setStats({
        total:      data.length,
        suspicious: data.filter(r => r.verdict === 'incorrect' || r.verdict === 'suspicious').length,
        cleared:    data.filter(r => r.verdict === 'correct' || r.verdict === 'legitimate').length,
        uncertain:  data.filter(r => r.verdict === 'uncertain').length,
        queued:     data.filter(r => r.verdict === 'queued').length,
        processing: data.filter(r => r.verdict === 'processing').length,
      })
    } catch (e) {
      console.error('[AgentLog]', e)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [log, autoScroll])

  return (
    <div className="page-container">
      <div className="page-title">Agent Processing Log</div>
      <div className="page-subtitle">
        Real-time event console — VAT fraud detection agent lifecycle
      </div>

      <div className="metrics-row" style={{ marginBottom: 16 }}>
        {[
          { label: 'Total entries',  value: stats.total,     sub: 'all events' },
          { label: 'Suspicious',     value: stats.suspicious, sub: '→ flagged', cls: stats.suspicious ? 'error-tile' : '' },
          { label: 'Cleared',        value: stats.cleared,    sub: 'no risk' },
          { label: 'Uncertain',      value: stats.uncertain,  sub: 'inconclusive' },
          { label: 'In queue',       value: (stats.queued || 0) + (stats.processing || 0), sub: 'pending' },
        ].map(t => (
          <div key={t.label} className={'metric-tile ' + (t.cls || '')}>
            <div className="metric-tile__label">{t.label}</div>
            <div className="metric-tile__value">{t.value}</div>
            <div className="metric-tile__sub">{t.sub}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 0 }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px',
          background: '#1a1a2e', borderRadius: 'var(--radius) var(--radius) 0 0',
          borderBottom: '1px solid #333',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 12, height: 12, borderRadius: '50%', background: '#ff5f57', display: 'inline-block' }} />
            <span style={{ width: 12, height: 12, borderRadius: '50%', background: '#febc2e', display: 'inline-block' }} />
            <span style={{ width: 12, height: 12, borderRadius: '50%', background: '#28c840', display: 'inline-block' }} />
            <span style={{ marginLeft: 8, fontSize: 11, color: '#8b8fa8',
                           fontFamily: '"Courier New", Courier, monospace' }}>
              eu-custom-hub — agent-processing-log
            </span>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6,
                          fontSize: 11, color: '#8b8fa8', cursor: 'pointer' }}>
            <input type="checkbox" checked={autoScroll}
                   onChange={e => setAutoScroll(e.target.checked)} />
            Auto-scroll
          </label>
        </div>

        <div style={{
          background: '#fafbfc',
          maxHeight: 520, overflowY: 'auto',
          borderRadius: '0 0 var(--radius) var(--radius)',
        }}>
          {log.length === 0 ? (
            <div style={{
              padding: '40px 20px', textAlign: 'center',
              fontFamily: '"Courier New", Courier, monospace',
              fontSize: 12, color: 'var(--text-muted)',
            }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
              No agent activity yet.
              <br /><br />
              <span style={{ fontSize: 11 }}>
                The agent processes cases submitted for tax review by customs officers.
                <br />
                Events will appear here when cases are created, queued, and analysed.
              </span>
            </div>
          ) : (
            log.map((entry, i) => (
              <LogLine key={entry.id || i} entry={entry} onDetails={setDetail} />
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <DetailDrawer entry={detail} onClose={() => setDetail(null)} />
    </div>
  )
}
