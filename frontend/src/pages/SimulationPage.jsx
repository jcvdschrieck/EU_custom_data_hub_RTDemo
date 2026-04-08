import { useState, useEffect, useCallback } from 'react'
import {
  getSimStatus, getPipelineStats,
  simStart, simPause, simResume, simReset, simSetSpeed,
} from '../api'

// Speed = sim-minutes per real-second.  Full March (44 640 sim-min):
//   10  → ~74 min   |  50  → ~15 min (default)  |  150 → ~5 min
//  450  → ~100 sec  | 1500 → ~30 sec
const SPEEDS = [
  { label: '10×',   value: 10   },
  { label: '50×',   value: 50   },
  { label: '150×',  value: 150  },
  { label: '450×',  value: 450  },
  { label: '1500×', value: 1500 },
]

function fmt(n) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-EU')
}

// ── Controls card ─────────────────────────────────────────────────────────────

function SimControls({ status, onRefresh }) {
  const [busy, setBusy] = useState(false)
  const act = useCallback(async (fn) => {
    setBusy(true)
    try { await fn() } finally { setBusy(false); onRefresh() }
  }, [onRefresh])

  if (!status) return (
    <div className="card">
      <div style={{ padding: 24, color: 'var(--text-muted)' }}>Connecting to simulation…</div>
    </div>
  )

  const { running, finished, pct_complete, speed, sim_time, fired_count, total, active_alarms } = status
  const stateLabel = finished ? 'Finished' : running ? 'Running' : fired_count ? 'Paused' : 'Ready'
  const stateColor = finished ? 'var(--text-muted)'
                   : running  ? 'var(--success)'
                   : fired_count ? 'var(--warning)'
                   : 'var(--eu-blue)'
  const dotClass = finished ? 'finished' : running ? 'running' : 'paused'
  const handleToggle = () => {
    if (finished) return
    act(running ? simPause : fired_count ? simResume : simStart)
  }

  return (
    <div className="card">
      <div className="card-header">Simulation Controls</div>
      <div style={{ padding: '20px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className={`sim-dot ${dotClass}`} style={{ width: 12, height: 12 }} />
            <span style={{ fontSize: 17, fontWeight: 700, color: stateColor }}>{stateLabel}</span>
          </div>
          <StatChip label="Sim date"    value={sim_time ? sim_time.slice(0, 10) : '—'} />
          <StatChip label="Fired"       value={`${fmt(fired_count)} / ${fmt(total)}`} />
          <StatChip label="Completion"  value={`${(pct_complete || 0).toFixed(1)}%`} />
          <StatChip label="Active alarms" value={fmt(active_alarms)} accent={active_alarms > 0 ? 'var(--error)' : null} />
        </div>

        <div style={{ height: 10, background: '#e9ecef', borderRadius: 5, marginBottom: 20, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${pct_complete || 0}%`,
            background: finished ? '#adb5bd' : running ? 'var(--eu-blue)' : 'var(--warning)',
            transition: 'width 0.6s ease', borderRadius: 5,
          }} />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button onClick={handleToggle} disabled={finished || busy} style={{
            background: running ? '#e9ecef' : 'var(--eu-blue)',
            color: running ? 'var(--text-primary)' : '#fff',
            border: 'none', borderRadius: 'var(--radius)', padding: '8px 22px',
            fontSize: 13, fontWeight: 700, cursor: finished || busy ? 'not-allowed' : 'pointer', minWidth: 110,
          }}>
            {running ? '⏸ Pause' : fired_count ? '▶ Resume' : '▶ Start'}
          </button>
          <button onClick={() => act(simReset)} disabled={busy} style={{
            background: '#f8f9fa', color: 'var(--text-primary)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer',
          }}>↺ Reset</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 12 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>Speed:</span>
            {SPEEDS.map(s => (
              <button key={s.value} onClick={() => act(() => simSetSpeed(s.value))} disabled={busy} style={{
                background: speed === s.value ? 'var(--eu-blue)' : '#f8f9fa',
                color: speed === s.value ? '#fff' : 'var(--text-primary)',
                border: `1px solid ${speed === s.value ? 'var(--eu-blue)' : 'var(--border)'}`,
                borderRadius: 'var(--radius)', padding: '5px 11px', fontSize: 12, fontWeight: 600,
                cursor: busy ? 'not-allowed' : 'pointer',
              }}>{s.label}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatChip({ label, value, accent }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: accent || 'var(--text-primary)' }}>{value}</div>
    </div>
  )
}

// ── Node primitives ───────────────────────────────────────────────────────────

function BrokerNode({ label, topicKey, count, queueSize, children, accent }) {
  const blue = accent || 'var(--eu-blue)'
  const bg   = accent ? accent + '18' : 'var(--eu-blue-light)'
  return (
    <div style={{
      background: bg, border: `2px solid ${blue}`,
      borderRadius: 'var(--radius)', padding: '8px 12px',
      minWidth: 140, textAlign: 'center', flex: '0 0 auto',
    }}>
      <div style={{ fontSize: 8, color: blue, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3, fontWeight: 700 }}>
        {topicKey}
      </div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 5, lineHeight: 1.3 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: blue, lineHeight: 1 }}>{fmt(count)}</div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>events</div>
      {queueSize > 0 && (
        <div style={{ marginTop: 4, fontSize: 9, color: 'var(--warning)', fontWeight: 700, background: '#fff8e6', borderRadius: 8, padding: '1px 5px', display: 'inline-block' }}>
          {queueSize} queued
        </div>
      )}
      {children}
    </div>
  )
}

function FactoryNode({ label, description, icon, accent }) {
  return (
    <div style={{
      background: accent ? accent + '12' : '#f8f9fa',
      border: `1px solid ${accent || 'var(--border)'}`,
      borderRadius: 10, padding: '7px 11px',
      minWidth: 130, textAlign: 'center', flex: '0 0 auto',
    }}>
      <div style={{ fontSize: 16, marginBottom: 2 }}>{icon}</div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>{label}</div>
      {description && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>}
    </div>
  )
}

function QueueNode({ label, count, accent = '#9c27b0' }) {
  return (
    <div style={{
      background: accent + '15', border: `2px dashed ${accent}`,
      borderRadius: 'var(--radius)', padding: '8px 12px',
      minWidth: 130, textAlign: 'center', flex: '0 0 auto',
    }}>
      <div style={{ fontSize: 14, marginBottom: 2 }}>📋</div>
      <div style={{ fontSize: 10, fontWeight: 700, color: accent, lineHeight: 1.3 }}>{label}</div>
      {count != null && (
        <div style={{ fontSize: 18, fontWeight: 700, color: accent, marginTop: 3 }}>{fmt(count)}</div>
      )}
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>FIFO queue</div>
    </div>
  )
}

function DBSinkNode({ count }) {
  return (
    <div style={{
      background: '#e8f0fe', border: '2px solid var(--eu-blue)',
      borderRadius: 'var(--radius)', padding: '8px 12px',
      minWidth: 130, textAlign: 'center', flex: '0 0 auto',
    }}>
      <div style={{ fontSize: 14, marginBottom: 2 }}>🏛️</div>
      <div style={{ fontSize: 9, color: 'var(--eu-blue)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 700, marginBottom: 3 }}>Custom Data Hub</div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4, lineHeight: 1.3 }}>Stored transactions</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--eu-blue)', lineHeight: 1 }}>{fmt(count)}</div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>records</div>
    </div>
  )
}

function Arrow({ label, down = false, color = '#adb5bd', dashed = false }) {
  const dash = dashed ? '4,3' : undefined
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', gap: 3, padding: down ? '2px 0' : '0 6px', flex: '0 0 auto',
    }}>
      {down ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <svg width={10} height={20}><line x1={5} y1={0} x2={5} y2={14} stroke={color} strokeWidth={2} strokeDasharray={dash} /><polygon points="1,14 9,14 5,20" fill={color} /></svg>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <svg width={28} height={10}><line x1={0} y1={5} x2={22} y2={5} stroke={color} strokeWidth={2} strokeDasharray={dash} /><polygon points="22,1 28,5 22,9" fill={color} /></svg>
        </div>
      )}
      {label && <div style={{ fontSize: 9, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{label}</div>}
    </div>
  )
}

function ZoneLabel({ children, color }) {
  return (
    <div style={{
      fontSize: 9, fontWeight: 700, color: color || 'var(--text-muted)',
      textTransform: 'uppercase', letterSpacing: '0.08em',
      textAlign: 'center', marginBottom: 6,
    }}>{children}</div>
  )
}

function Zone({ label, labelColor, children, style }) {
  return (
    <div style={{
      border: '1px dashed var(--border-light)', borderRadius: 6,
      padding: '8px 10px', flex: '0 0 auto', ...style,
    }}>
      {label && <ZoneLabel color={labelColor}>{label}</ZoneLabel>}
      {children}
    </div>
  )
}

function FlaggedBadge({ flagged, total }) {
  if (!total) return null
  const pct = ((flagged ?? 0) / total * 100).toFixed(0)
  return (
    <div style={{ marginTop: 4, display: 'flex', justifyContent: 'center' }}>
      <span style={{ background: '#fde8e8', color: 'var(--error)', border: '1px solid #f5c6cb', padding: '1px 6px', borderRadius: 8, fontSize: 9, fontWeight: 700 }}>
        ⚑ {fmt(flagged)} ({pct}%)
      </span>
    </div>
  )
}

function ScoreBadges({ green, amber, red }) {
  if (green == null && amber == null && red == null) return null
  return (
    <div style={{ marginTop: 5, display: 'flex', justifyContent: 'center', gap: 3, flexWrap: 'wrap' }}>
      <span style={{ background: '#d4edda', color: '#155724', border: '1px solid #c3e6cb', padding: '1px 5px', borderRadius: 8, fontSize: 9, fontWeight: 700 }}>● {fmt(green)}</span>
      <span style={{ background: '#fff3cd', color: '#856404', border: '1px solid #ffc107', padding: '1px 5px', borderRadius: 8, fontSize: 9, fontWeight: 700 }}>● {fmt(amber)}</span>
      <span style={{ background: '#fde8e8', color: '#c0392b', border: '1px solid #f5c6cb', padding: '1px 5px', borderRadius: 8, fontSize: 9, fontWeight: 700 }}>● {fmt(red)}</span>
    </div>
  )
}

// ── SVG fan-out / fan-in connectors ──────────────────────────────────────────

function FanOutSVG({ height, targetYs, color = '#adb5bd', width = 48, dashed = false }) {
  if (!targetYs || !targetYs.length) return null
  const spineX = 8
  const y0 = targetYs[0], y1 = targetYs[targetYs.length - 1]
  const dash = dashed ? '4,3' : undefined
  return (
    <svg width={width} height={height} style={{ flex: `0 0 ${width}px`, overflow: 'visible' }}>
      <line x1={spineX} y1={y0} x2={spineX} y2={y1} stroke={color} strokeWidth={2} strokeDasharray={dash} />
      {targetYs.map((yc, i) => (
        <g key={i}>
          <circle cx={spineX} cy={yc} r={3} fill={color} />
          <line x1={spineX} y1={yc} x2={width - 6} y2={yc} stroke={color} strokeWidth={2} strokeDasharray={dash} />
          <polygon points={`${width-6},${yc-4} ${width},${yc} ${width-6},${yc+4}`} fill={color} />
        </g>
      ))}
    </svg>
  )
}

// Fan-out with per-target color + dash (used for entry broker → mixed lanes)
function FanOutMixedSVG({ height, targets, width = 56 }) {
  if (!targets?.length) return null
  const spineX = 8
  const ys = targets.map(t => t.y)
  const y0 = Math.min(...ys), y1 = Math.max(...ys)
  return (
    <svg width={width} height={height} style={{ flex: `0 0 ${width}px`, overflow: 'visible' }}>
      <line x1={spineX} y1={y0} x2={spineX} y2={y1} stroke="#adb5bd" strokeWidth={2} />
      {targets.map((t, i) => {
        const dash = t.dashed ? '4,3' : undefined
        const col  = t.color || '#adb5bd'
        return (
          <g key={i}>
            <circle cx={spineX} cy={t.y} r={3} fill={col} />
            <line x1={spineX} y1={t.y} x2={width - 6} y2={t.y}
              stroke={col} strokeWidth={2} strokeDasharray={dash} />
            <polygon points={`${width-6},${t.y-4} ${width},${t.y} ${width-6},${t.y+4}`} fill={col} />
          </g>
        )
      })}
    </svg>
  )
}

function FanInSVG({ height, inputYs, outputY, color = '#adb5bd', width = 48 }) {
  if (!inputYs || !inputYs.length) return null
  const spineX = width - 8
  const y0 = inputYs[0], y1 = inputYs[inputYs.length - 1]
  return (
    <svg width={width} height={height} style={{ flex: `0 0 ${width}px`, overflow: 'visible' }}>
      <line x1={spineX} y1={y0} x2={spineX} y2={y1} stroke={color} strokeWidth={2} />
      {inputYs.map((yc, i) => (
        <g key={i}>
          <line x1={0} y1={yc} x2={spineX} y2={yc} stroke={color} strokeWidth={2} />
          <circle cx={spineX} cy={yc} r={3} fill={color} />
        </g>
      ))}
      <polygon points={`${spineX},${outputY-4} ${width},${outputY} ${spineX},${outputY+4}`} fill={color} />
    </svg>
  )
}

// ── Pipeline Diagram ──────────────────────────────────────────────────────────

function PipelineDiagram({ pipeline }) {
  const ev     = pipeline?.events             || {}
  const q      = pipeline?.queues             || {}
  const rf     = pipeline?.risk_flags         || {}
  const inv    = pipeline?.investigation_queue ?? null
  const stored = pipeline?.stored_count        ?? null

  // Fixed row heights for the three parallel lanes
  const OV_H   = 80
  const RT_H   = 210
  const AN_H   = 80
  const LGAP   = 16
  const totalH = OV_H + LGAP + RT_H + LGAP + AN_H  // 402

  // y-center of each lane (for SVG fan-out from entry broker)
  const yOV = OV_H / 2                                    // 40
  const yRT = OV_H + LGAP + RT_H / 2                      // 201
  const yAN = OV_H + LGAP + RT_H + LGAP + AN_H / 2       // 362

  // Routing section: three well-spread output rows
  const RROW  = 100
  const RGAP  = 20
  const routeH = RROW * 3 + RGAP * 2  // 340
  const ryG   = RROW / 2                                   // 50
  const ryR   = RROW + RGAP + RROW / 2                     // 170
  const ryA   = RROW * 2 + RGAP * 2 + RROW / 2            // 290

  // DB fan-in: only green + red feed directly into DB Store Factory
  const dbH   = ryR + RROW / 2 - ryG + RROW / 2           // spans green row center to red row center
  // inputYs relative to a container starting at ryG - RROW/2
  const dbIn0 = ryG
  const dbIn1 = ryR

  return (
    <div className="card section-gap">
      <div className="card-header">
        Pipeline Flow
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>auto-refresh every 3 s</span>
      </div>

      {/* ── MAIN PIPELINE ── */}
      <div style={{ overflowX: 'auto', padding: '20px 20px 4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', minWidth: 'max-content', gap: 0 }}>

          {/* 1. Entry Broker */}
          <Zone label="Entry Broker">
            <BrokerNode
              label="Sales-order Event Broker"
              topicKey="SALES_ORDER_EVENT"
              count={ev.sales_order_event}
              queueSize={q.sales_order_event}
            />
          </Zone>

          {/* 2. Mixed fan-out: solid → OV + RT  |  dashed orange → Transport */}
          <FanOutMixedSVG height={totalH} width={56} targets={[
            { y: yOV, color: '#adb5bd', dashed: false },
            { y: yRT, color: '#adb5bd', dashed: false },
            { y: yAN, color: '#e67e22', dashed: true  },
          ]} />

          {/* 3. Factory column (variable width, rows fixed height) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>

            {/* OV factory row */}
            <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
              <FactoryNode icon="✅" label="Order Validation" description="3–5 s · unlimited" />
            </div>

            {/* RT Risk block */}
            <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
              <Zone label="RT Risk Monitoring" style={{ width: '100%' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <FactoryNode icon="⚖️" label="RT Risk Mon. 1" description="VAT ratio deviation" />
                    <Arrow />
                    <BrokerNode label="RT Risk 1 Outcome" topicKey="RT_RISK_1_OUTCOME"
                      count={ev.rt_risk_1_outcome} queueSize={q.rt_risk_1_outcome}>
                      <FlaggedBadge flagged={rf.rt_risk_1_flagged} total={ev.rt_risk_1_outcome} />
                    </BrokerNode>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <FactoryNode icon="🔍" label="RT Risk Mon. 2" description="Watchlist lookup" />
                    <Arrow />
                    <BrokerNode label="RT Risk 2 Outcome" topicKey="RT_RISK_2_OUTCOME"
                      count={ev.rt_risk_2_outcome} queueSize={q.rt_risk_2_outcome}>
                      <FlaggedBadge flagged={rf.rt_risk_2_flagged} total={ev.rt_risk_2_outcome} />
                    </BrokerNode>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 4 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                      <svg width={64} height={18}>
                        <line x1={14} y1={0} x2={32} y2={14} stroke="#adb5bd" strokeWidth={1.5} />
                        <line x1={50} y1={0} x2={32} y2={14} stroke="#adb5bd" strokeWidth={1.5} />
                        <polygon points="28,12 36,12 32,18" fill="#adb5bd" />
                      </svg>
                      <FactoryNode icon="🔄" label="RT Consolidation" description="GREEN / AMBER / RED" />
                    </div>
                  </div>
                </div>
              </Zone>
            </div>

            {/* Transport row — merged transport + arrival factory */}
            <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
              <FactoryNode icon="🚢" label="Transport" description="exp. delay ~60 s · unlimited" accent="#e67e22" />
            </div>

          </div>

          {/* 4. Arrows: factory → brokers */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>
            <div style={{ height: OV_H,   display: 'flex', alignItems: 'center' }}><Arrow /></div>
            <div style={{ height: RT_H,   display: 'flex', alignItems: 'center' }}><Arrow /></div>
            <div style={{ height: AN_H,   display: 'flex', alignItems: 'center' }}><Arrow color="#e67e22" /></div>
          </div>

          {/* 5. Brokers column — all three aligned on same vertical */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>
            <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
              <BrokerNode label="Order Validation" topicKey="ORDER_VALIDATION"
                count={ev.order_validation} queueSize={q.order_validation} />
            </div>
            <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
              <BrokerNode label="RT Score" topicKey="RT_SCORE"
                count={ev.rt_score} queueSize={q.rt_score}>
                <ScoreBadges green={rf.rt_score_green} amber={rf.rt_score_amber} red={rf.rt_score_red} />
              </BrokerNode>
            </div>
            <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
              <BrokerNode label="Arrival Notification" topicKey="ARRIVAL_NOTIFICATION"
                count={ev.arrival_notification} queueSize={q.arrival_notification} accent="#e67e22" />
            </div>
          </div>

          {/* 6. Fan-in: all three brokers → Risk Routing Factory */}
          <FanInSVG height={totalH} inputYs={[yOV, yRT, yAN]} outputY={totalH / 2} width={52} />

          {/* 7. Risk Routing Factory — single node, routes by score */}
          <Zone label="Risk Routing">
            <FactoryNode icon="🎯" label="Risk Routing Factory" description="routes by score + validation" />
          </Zone>

          {/* 8. Fan-out: one factory → three event brokers */}
          <FanOutSVG height={routeH} targetYs={[ryG, ryR, ryA]} width={52} />

          {/* 9. Three event brokers — well spread */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: RGAP, height: routeH }}>

            <div style={{ height: RROW, display: 'flex', alignItems: 'center' }}>
              <BrokerNode label="Release Event" topicKey="RELEASE_EVENT"
                count={ev.release_event} queueSize={q.release_event} accent="#1f7a3c" />
            </div>

            <div style={{ height: RROW, display: 'flex', alignItems: 'center' }}>
              <BrokerNode label="Retain Event" topicKey="RETAIN_EVENT"
                count={ev.retain_event} queueSize={q.retain_event} accent="#c0392b" />
            </div>

            <div style={{ height: RROW, display: 'flex', alignItems: 'center' }}>
              <BrokerNode label="Investigate Event" topicKey="INVESTIGATE_EVENT"
                count={ev.investigate_event} queueSize={q.investigate_event} accent="#e6820a">
                <div style={{ fontSize: 9, color: '#e6820a', marginTop: 4, fontWeight: 700 }}>↓ investigation pipeline</div>
              </BrokerNode>
            </div>

          </div>

          {/* 10. Fan-in: Release + Retain → DB Store Factory */}
          <FanInSVG height={routeH} inputYs={[ryG, ryR]} outputY={(ryG + ryR) / 2} width={48} color="#1f7a3c" />

          {/* 11. DB Store Factory + DB Sink */}
          <Zone label="Sink">
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
              <FactoryNode icon="💾" label="DB Store Factory" description="Insert + flag suspicious" />
              <Arrow down />
              <DBSinkNode count={stored} />
            </div>
          </Zone>

        </div>
      </div>

      {/* ── INVESTIGATION SUB-PIPELINE ── */}
      <div style={{ margin: '4px 20px 4px', padding: '12px 14px', background: '#fdf6ff', border: '1.5px solid #9c27b066', borderRadius: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#7b1fa2', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
          Investigation Sub-Pipeline — from Investigate Event broker (AMBER / Ireland)
        </div>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 0, minWidth: 'max-content' }}>

            {/* Source label (links visually to the amber broker above) */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginRight: 6 }}>
              <div style={{ fontSize: 9, color: '#e6820a', fontWeight: 700, border: '1px dashed #e6820a', borderRadius: 4, padding: '2px 6px', whiteSpace: 'nowrap' }}>
                INVESTIGATE_EVENT
              </div>
              <Arrow color="#e6820a" />
            </div>

            <FactoryNode icon="🕵️" label="Investigator Factory" description="IE filter · FIFO queue" accent="#9c27b0" />
            <Arrow color="#9c27b0" />
            <QueueNode label="Investigation Queue" count={inv} accent="#9c27b0" />
            <Arrow color="#9c27b0" />
            <FactoryNode icon="🤖" label="VAT Agent Worker" description="LM Studio · fraud detection" accent="#9c27b0" />

            {/* Fork: incorrect vs correct/uncertain */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginLeft: 6 }}>

              {/* Incorrect → retain */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Arrow color="#c0392b" label="incorrect" />
                <BrokerNode label="Retained after Inv." topicKey="AGENT_RETAIN_EVENT"
                  count={ev.agent_retain_event} queueSize={q.agent_retain_event} accent="#c0392b" />
                <Arrow color="#c0392b" />
                <div style={{ fontSize: 9, color: '#c0392b', fontWeight: 700, border: '1px dashed #c0392b', borderRadius: 4, padding: '2px 6px' }}>→ DB Store Factory</div>
              </div>

              {/* Correct/uncertain → release after investigation */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Arrow color="#1f7a3c" label="correct/uncertain" />
                <BrokerNode label="To Be Released after Inv." topicKey="AGENT_RELEASE_EVENT"
                  count={ev.agent_release_event} queueSize={q.agent_release_event} accent="#1f7a3c" />
                <Arrow color="#1f7a3c" />
                <FactoryNode icon="🔓" label="Release After Inv. Factory" description="agent-release + OV + arrival" accent="#1f7a3c" />
                <Arrow color="#1f7a3c" />
                <BrokerNode label="Release After Investigation" topicKey="RELEASE_AFTER_INVESTIGATION_EVENT"
                  count={ev.release_after_investigation_event}
                  queueSize={q.release_after_investigation_event} accent="#1f7a3c" />
                <Arrow color="#1f7a3c" />
                <div style={{ fontSize: 9, color: '#1f7a3c', fontWeight: 700, border: '1px dashed #1f7a3c', borderRadius: 4, padding: '2px 6px' }}>→ DB Store Factory</div>
              </div>

            </div>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div style={{ padding: '10px 20px 16px', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', borderTop: '1px solid var(--border-light)' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)' }}>Legend:</span>
        <LegendItem color="var(--eu-blue)" bg="var(--eu-blue-light)" label="Broker" />
        <LegendItem color="var(--border)" bg="#f8f9fa" label="Factory" />
        <LegendItem color="#1f7a3c" bg="#e8f5e9" label="GREEN — release" />
        <LegendItem color="#c0392b" bg="#fde8e8" label="RED — retain" />
        <LegendItem color="#e6820a" bg="#fff3e0" label="AMBER — investigate" />
        <LegendItem color="#9c27b0" bg="#fdf6ff" label="Investigation pipeline" />
        <LegendItem color="#e67e22" bg="#fff8f0" label="Transport / Arrival (dashed)" dashed />
        <div style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
          Counts reflect JSON events persisted to <code>data/events/</code> since last reset.
        </div>
      </div>
    </div>
  )
}

function LegendItem({ color, bg, label, dashed }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{
        width: 14, height: 14, background: bg,
        border: `2px ${dashed ? 'dashed' : 'solid'} ${color}`, borderRadius: 2,
      }} />
      <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{label}</span>
    </div>
  )
}

// ── Event counts table ────────────────────────────────────────────────────────

const TOPIC_META = [
  { key: 'sales_order_event',                   label: 'Sales-order Event Broker',        factory: 'Simulation loop',                    color: '#0050a0' },
  { key: 'order_validation',                    label: 'Order Validation',                 factory: 'Order Validation Factory',           color: '#1f7a3c' },
  { key: 'rt_risk_1_outcome',                   label: 'RT Risk 1 Outcome',                factory: 'RT Risk Monitoring 1',               color: '#6f42c1' },
  { key: 'rt_risk_2_outcome',                   label: 'RT Risk 2 Outcome',                factory: 'RT Risk Monitoring 2',               color: '#6f42c1' },
  { key: 'rt_score',                            label: 'RT Score',                         factory: 'RT Consolidation Factory',            color: '#e6820a' },
  { key: 'arrival_notification',                label: 'Arrival Notification',             factory: 'Arrival Notification Factory',        color: '#e67e22' },
  { key: 'release_event',                       label: 'Release Event',                    factory: 'Release Factory (GREEN)',             color: '#1f7a3c' },
  { key: 'retain_event',                        label: 'Retain Event',                     factory: 'Retain Factory (RED)',                color: '#c0392b' },
  { key: 'investigate_event',                   label: 'Investigate Event',                factory: 'Investigate Dispatch Factory (AMBER)', color: '#e6820a' },
  { key: 'agent_retain_event',                  label: 'Retained after Investigation',     factory: 'Investigation Agent Worker',          color: '#c0392b' },
  { key: 'agent_release_event',                 label: 'To Be Released after Investigation', factory: 'Investigation Agent Worker',        color: '#1f7a3c' },
  { key: 'release_after_investigation_event',   label: 'Release after Investigation',      factory: 'Release After Investigation Factory', color: '#2e7d32' },
]

function EventCountsTable({ pipeline }) {
  const ev    = pipeline?.events || {}
  const q     = pipeline?.queues || {}
  const total = Object.values(ev).reduce((s, v) => s + (v || 0), 0)

  return (
    <div className="card">
      <div className="card-header">Event Counts by Topic</div>
      <div className="tx-table-wrap">
        <table className="tx-table">
          <thead>
            <tr>
              <th>Topic</th>
              <th>Published by</th>
              <th style={{ textAlign: 'right' }}>Events persisted</th>
              <th style={{ textAlign: 'right' }}>Live queue</th>
              <th style={{ textAlign: 'right' }}>% of total</th>
            </tr>
          </thead>
          <tbody>
            {TOPIC_META.map(t => {
              const count = ev[t.key] ?? 0
              const queue = q[t.key] ?? 0
              const pct   = total > 0 ? (count / total * 100) : 0
              return (
                <tr key={t.key}>
                  <td>
                    <span style={{
                      background: t.color + '18', color: t.color,
                      border: `1px solid ${t.color}40`,
                      padding: '2px 8px', borderRadius: 8, fontSize: 11, fontWeight: 700,
                    }}>{t.key}</span>
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>{t.factory}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(count)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {queue > 0
                      ? <span style={{ color: 'var(--warning)', fontWeight: 700 }}>{queue}</span>
                      : <span style={{ color: 'var(--text-muted)' }}>0</span>}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
                      <div style={{ width: 60, height: 6, background: '#e9ecef', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: t.color, borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-secondary)', minWidth: 36, textAlign: 'right' }}>
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2} style={{ fontWeight: 700, color: 'var(--text-secondary)', paddingTop: 8 }}>Total</td>
              <td style={{ textAlign: 'right', fontWeight: 700, paddingTop: 8 }}>{fmt(total)}</td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SimulationPage() {
  const [status,   setStatus]   = useState(null)
  const [pipeline, setPipeline] = useState(null)

  const refreshStatus   = useCallback(async () => { try { setStatus(await getSimStatus()) } catch {} }, [])
  const refreshPipeline = useCallback(async () => { try { setPipeline(await getPipelineStats()) } catch {} }, [])

  useEffect(() => {
    refreshStatus()
    const id = setInterval(refreshStatus, 2000)
    return () => clearInterval(id)
  }, [refreshStatus])

  useEffect(() => {
    refreshPipeline()
    const id = setInterval(refreshPipeline, 3000)
    return () => clearInterval(id)
  }, [refreshPipeline])

  return (
    <div className="page-container">
      <div className="page-title">Simulation</div>
      <div className="page-subtitle">
        Control the simulation and monitor the pub/sub pipeline in real time
      </div>

      <SimControls status={status} onRefresh={() => { refreshStatus(); refreshPipeline() }} />
      <PipelineDiagram pipeline={pipeline} status={status} />
      <EventCountsTable pipeline={pipeline} />
    </div>
  )
}
