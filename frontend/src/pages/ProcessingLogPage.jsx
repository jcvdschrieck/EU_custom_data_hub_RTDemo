import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'

function fmt(n, dec = 2) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

const VERDICT = {
  incorrect: { icon: '❌', color: 'var(--error)',   bg: '#fff0f0', label: 'INCORRECT' },
  correct:   { icon: '✅', color: 'var(--success)', bg: '#f0fff4', label: 'CORRECT'   },
  uncertain: { icon: '❓', color: '#856404',        bg: '#fffbe6', label: 'UNCERTAIN'  },
  processing:{ icon: '⚙️', color: '#005ea2',        bg: '#e8f1f8', label: 'PROCESSING' },
}

// ── Detail drawer ─────────────────────────────────────────────────────────────

function DetailDrawer({ entry, onClose }) {
  if (!entry) return null
  const v = VERDICT[entry.verdict] || VERDICT.uncertain
  const refs = entry.legislation_refs || []

  return (
    <>
      {/* Overlay */}
      <div onClick={onClose} style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 900,
      }} />
      {/* Drawer */}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 480,
        background: '#fff', zIndex: 901,
        boxShadow: '-4px 0 24px rgba(0,0,0,0.18)',
        display: 'flex', flexDirection: 'column',
        overflowY: 'auto',
      }}>
        {/* Header */}
        <div style={{
          background: v.bg, borderBottom: `3px solid ${v.color}`,
          padding: '16px 20px', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', gap: 12,
        }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>
              Agent Analysis Detail
            </div>
            <div style={{ fontWeight: 700, fontSize: 15, color: v.color }}>
              {v.icon} {v.label}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4 }}>
              {entry.transaction_id}
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: '1px solid var(--border)',
            borderRadius: 6, padding: '4px 10px', cursor: 'pointer',
            fontSize: 16, color: 'var(--text-secondary)',
          }}>✕</button>
        </div>

        <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Transaction info */}
          <section>
            <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--text-secondary)',
                          textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
              Transaction
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 12 }}>
              {[
                ['Seller',    entry.seller_name],
                ['Buyer',     entry.buyer_country],
                ['Item',      entry.item_description],
                ['Category',  entry.item_category],
                ['Value',     `€ ${fmt(entry.value)}`],
                ['Applied VAT', `${(entry.vat_rate * 100).toFixed(1)}%`],
                ['Correct VAT', `${(entry.correct_vat_rate * 100).toFixed(1)}%`],
                ['Processed', entry.processed_at?.slice(0, 19).replace('T', ' ')],
              ].map(([k, val]) => (
                <div key={k}>
                  <span style={{ color: 'var(--text-muted)' }}>{k}: </span>
                  <strong>{val}</strong>
                </div>
              ))}
            </div>
          </section>

          {/* Full reasoning */}
          <section>
            <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--text-secondary)',
                          textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
              Agent Reasoning
            </div>
            <div style={{
              background: '#f8f9fa', border: '1px solid var(--border)',
              borderRadius: 6, padding: '10px 12px',
              fontSize: 12, lineHeight: 1.6, color: DARK_TEXT,
              whiteSpace: 'pre-wrap',
            }}>
              {entry.reasoning || '—'}
            </div>
          </section>

          {/* Legislation references */}
          <section>
            <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--text-secondary)',
                          textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
              Legislation References ({refs.length})
            </div>
            {refs.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                No legislation references recorded for this analysis.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {refs.map((r, i) => (
                  <div key={i} style={{
                    background: '#f8f9fa', border: '1px solid var(--border)',
                    borderLeft: '3px solid var(--primary)',
                    borderRadius: 6, padding: '10px 12px',
                  }}>
                    <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--primary)' }}>
                      {r.ref && <span style={{ marginRight: 6 }}>{r.ref}</span>}
                      {r.source}
                    </div>
                    {r.section && (
                      <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                        {r.section}{r.page ? ` · p. ${r.page}` : ''}
                      </div>
                    )}
                    {r.paragraph && (
                      <div style={{
                        fontSize: 11, color: DARK_TEXT, marginTop: 6,
                        fontStyle: 'italic', lineHeight: 1.5,
                        borderTop: '1px solid var(--border)', paddingTop: 6,
                      }}>
                        "{r.paragraph}"
                      </div>
                    )}
                    {r.url && (
                      <div style={{ marginTop: 4 }}>
                        <a href={r.url} target="_blank" rel="noreferrer"
                           style={{ fontSize: 10, color: 'var(--primary)' }}>
                          Source ↗
                        </a>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

        </div>
      </div>
    </>
  )
}

const DARK_TEXT = '#1a1a2e'

// ── Console log line ──────────────────────────────────────────────────────────

function LogLine({ entry, onDetails }) {
  const isProcessing = entry.type === 'processing'
  const v = VERDICT[isProcessing ? 'processing' : entry.verdict] || VERDICT.uncertain

  const ts = isProcessing
    ? entry.started_at?.slice(11, 19)
    : entry.processed_at?.slice(11, 19)

  const msg = isProcessing
    ? `Processing transaction ${entry.transaction_id?.slice(-8).toUpperCase()} · ${entry.seller_name} — ${entry.item_description} · €${fmt(entry.value)} · VAT ${(entry.vat_rate * 100).toFixed(1)}%`
    : entry.verdict === 'incorrect'
      ? `Transaction ${entry.transaction_id?.slice(-8).toUpperCase()} · verdict: INCORRECT — ${(entry.vat_rate * 100).toFixed(1)}% applied, ${(entry.correct_vat_rate * 100).toFixed(1)}% expected · forwarded to Ireland Revenue queue`
      : `Transaction ${entry.transaction_id?.slice(-8).toUpperCase()} · verdict: ${entry.verdict?.toUpperCase()} — ${entry.seller_name} · suspicious flag cleared`

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '7px 14px',
      borderBottom: '1px solid rgba(0,0,0,0.05)',
      background: isProcessing ? v.bg : entry.verdict === 'incorrect' ? '#fff8f8'
                : entry.verdict === 'correct' ? '#f6fff8' : '#fffdf0',
      fontFamily: '"Courier New", Courier, monospace',
    }}>
      {/* Timestamp */}
      <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap',
                     minWidth: 60, paddingTop: 1 }}>
        {ts || '—'}
      </span>

      {/* Icon */}
      <span style={{ fontSize: 14, minWidth: 20, paddingTop: 1 }}>{v.icon}</span>

      {/* Message */}
      <span style={{ fontSize: 11.5, color: DARK_TEXT, flex: 1, lineHeight: 1.5 }}>
        {isProcessing
          ? <><span style={{ color: v.color, fontWeight: 700 }}>[PROCESSING] </span>{msg}</>
          : <><span style={{ color: v.color, fontWeight: 700 }}>[{v.label}] </span>{msg}</>
        }
      </span>

      {/* Details button */}
      {!isProcessing && (
        <button onClick={() => onDetails(entry)} style={{
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
          fontSize: 10, color: 'var(--primary)', whiteSpace: 'nowrap',
          fontFamily: 'inherit',
        }}>
          Details ↗
        </button>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ProcessingLogPage() {
  const [log,        setLog]        = useState([])
  const [detail,     setDetail]     = useState(null)
  const [stats,      setStats]      = useState(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      // Historical log of every VAT Fraud Detection Agent run, populated by
      // POST /api/tax/{id}/run-agent on the new two-entity flow. Live in-flight
      // tracking now lives on the Tax Authority page in the Revenue Guardian
      // UI (agent_status field on the Tax queue), so this view is purely
      // historical.
      const logRes  = await axios.get('/api/agent-log?limit=500')
      const logData = logRes.data

      // Log is newest-first from API; reverse to oldest-first for console display
      const chronological = [...logData].reverse()
      setLog(chronological)

      const total     = logData.length
      const incorrect = logData.filter(r => r.verdict === 'incorrect').length
      const correct   = logData.filter(r => r.verdict === 'correct').length
      const uncertain = logData.filter(r => r.verdict === 'uncertain').length
      setStats({ total, incorrect, correct, uncertain })
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  // Auto-scroll to bottom (latest entry)
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [log, autoScroll])

  // All entries in chronological display order
  const allEntries = log

  return (
    <div className="page-container">
      <div className="page-title">Agent Processing Log</div>
      <div className="page-subtitle">
        Real-time event console — VAT fraud detection agent analysis of suspicious Ireland-bound transactions
      </div>

      {/* Stats */}
      {stats && (
        <div className="metrics-row" style={{ marginBottom: 16 }}>
          {[
            { label: 'Total processed', value: stats.total,     sub: 'by agent' },
            { label: 'Incorrect',       value: stats.incorrect, sub: '→ Ireland queue', cls: stats.incorrect ? 'error-tile' : '' },
            { label: 'Correct',         value: stats.correct,   sub: 'cleared' },
            { label: 'Uncertain',       value: stats.uncertain, sub: 'cleared' },
          ].map(t => (
            <div key={t.label} className={`metric-tile ${t.cls || ''}`}>
              <div className="metric-tile__label">{t.label}</div>
              <div className="metric-tile__value">{t.value}</div>
              <div className="metric-tile__sub">{t.sub}</div>
            </div>
          ))}
        </div>
      )}

      {/* Console */}
      <div className="card" style={{ padding: 0 }}>
        {/* Console header */}
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

        {/* Log body */}
        <div style={{
          background: '#fafbfc',
          maxHeight: 520, overflowY: 'auto',
          borderRadius: '0 0 var(--radius) var(--radius)',
        }}>
          {allEntries.length === 0 ? (
            <div style={{
              padding: '40px 20px', textAlign: 'center',
              fontFamily: '"Courier New", Courier, monospace',
              fontSize: 12, color: 'var(--text-muted)',
            }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
              Waiting for suspicious Ireland-bound transactions…
              <br />
              <span style={{ fontSize: 11 }}>
                Scenario: TechZone GmbH → IE alarm fires during week 2 of March 2026.
              </span>
            </div>
          ) : (
            allEntries.map((entry, i) => (
              <LogLine key={entry.id ?? `proc-${i}`} entry={entry} onDetails={setDetail} />
            ))
          )}
          {/* Blinking cursor */}
          {processing.length > 0 && (
            <div style={{ padding: '6px 14px', fontFamily: '"Courier New", monospace',
                          fontSize: 12, color: '#005ea2' }}>
              <span style={{ animation: 'blink 1s step-end infinite' }}>█</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <style>{`
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
      `}</style>

      {/* Detail drawer */}
      <DetailDrawer entry={detail} onClose={() => setDetail(null)} />
    </div>
  )
}
