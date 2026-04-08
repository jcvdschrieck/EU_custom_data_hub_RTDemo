import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getSimStatus, getPipelineStats,
  simStart, simPause, simResume, simReset, simSetSpeed,
} from '../api'

const SPEEDS = [
  { label: '1×',    value: 1 },
  { label: '30×',   value: 30 },
  { label: '120×',  value: 120 },
  { label: '360×',  value: 360 },
  { label: '1440×', value: 1440 },
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

function PipelineDiagram({ pipeline, status }) {
  const ev  = pipeline?.events            || {}
  const q   = pipeline?.queues            || {}
  const rf  = pipeline?.risk_flags        || {}
  const inv = pipeline?.investigation_queue ?? null
  const stored = pipeline?.stored_count ?? null

  const GAP = 14

  // Measure lane heights for exact SVG connector alignment
  const laneOVRef  = useRef(null)
  const laneRTRef  = useRef(null)
  const laneANRef  = useRef(null)
  const [laneH, setLaneH] = useState([80, 180, 80])

  useEffect(() => {
    const h = [
      laneOVRef.current?.offsetHeight ?? 80,
      laneRTRef.current?.offsetHeight ?? 180,
      laneANRef.current?.offsetHeight ?? 80,
    ]
    setLaneH(prev => h.every((v, i) => v === prev[i]) ? prev : h)
  })

  const [h0, h1, h2] = laneH
  const totalH = h0 + GAP + h1 + GAP + h2
  const yc0    = h0 / 2
  const yc1    = h0 + GAP + h1 / 2
  const yc2    = h0 + GAP + h1 + GAP + h2 / 2

  // ── Routing section: three output rows from RT Score
  const routeRowH = 72
  const routeGap  = 10
  const routeTotalH = routeRowH * 3 + routeGap * 2
  // y-centers for Green / Red / Amber rows (top-aligned to routeTotalH)
  const ryGreen = routeRowH / 2
  const ryRed   = routeRowH + routeGap + routeRowH / 2
  const ryAmber = routeRowH * 2 + routeGap * 2 + routeRowH / 2

  const laneBox = (accent) => ({
    border: `2px solid ${accent}`, borderRadius: 6, padding: '8px 10px',
    display: 'flex', alignItems: 'center', gap: 8,
  })

  return (
    <div className="card section-gap">
      <div className="card-header">
        Pipeline Flow
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>auto-refresh every 3 s</span>
      </div>

      {/* ── MAIN PIPELINE ── */}
      <div style={{ overflowX: 'auto', padding: '20px 20px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', minWidth: 'max-content', gap: 0 }}>

          {/* Col 1: Entry Broker — vertically spans OV + RT Risk lanes */}
          <div style={{ height: totalH, display: 'flex', flexDirection: 'column', justifyContent: 'flex-start' }}>
            <div style={{ height: h0 + GAP + h1, display: 'flex', alignItems: 'center' }}>
              <Zone label="Entry Broker">
                <BrokerNode
                  label="Sales-order Event Broker"
                  topicKey="SALES_ORDER_EVENT"
                  count={ev.sales_order_event}
                  queueSize={q.sales_order_event}
                />
              </Zone>
            </div>
          </div>

          {/* Col 2: Fan-out — OV and RT Risk lanes (solid); Arrival lane (dashed) */}
          <FanOutSVG height={totalH} targetYs={[yc0, yc1]} width={48} />

          {/* Col 3: Three parallel lanes */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>

            {/* Lane A: Order Validation */}
            <div ref={laneOVRef}>
              <ZoneLabel>Order Validation</ZoneLabel>
              <div style={laneBox('#1f7a3c')}>
                <FactoryNode icon="✅" label="Order Validation" description="Field completeness" />
                <Arrow />
                <BrokerNode label="Order Validation" topicKey="ORDER_VALIDATION"
                  count={ev.order_validation} queueSize={q.order_validation} />
              </div>
            </div>

            {/* Lane B: RT Risk Monitoring */}
            <div ref={laneRTRef}>
              <ZoneLabel>RT Risk Monitoring</ZoneLabel>
              <div style={laneBox('#6f42c1')}>
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
                </div>
                <Arrow label="merge" />
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <FactoryNode icon="🔄" label="RT Consolidation" description="GREEN / AMBER / RED" />
                  <Arrow down />
                  <BrokerNode label="RT Score" topicKey="RT_SCORE"
                    count={ev.rt_score} queueSize={q.rt_score}>
                    <ScoreBadges green={rf.rt_score_green} amber={rf.rt_score_amber} red={rf.rt_score_red} />
                  </BrokerNode>
                </div>
              </div>
            </div>

            {/* Lane C: Arrival Notification (dotted — triggered by goods transport, not by broker) */}
            <div ref={laneANRef}>
              <ZoneLabel color="#e67e22">Goods Transport → Arrival Notification</ZoneLabel>
              <div style={{ ...laneBox('#e67e22'), borderStyle: 'dashed' }}>
                <FactoryNode icon="🚢" label="Transport" description="exponential delay" accent="#e67e22" />
                <Arrow dashed color="#e67e22" />
                <FactoryNode icon="📦" label="Arrival Notif. Factory" description="goods available" accent="#e67e22" />
                <Arrow color="#e67e22" />
                <BrokerNode label="Arrival Notification" topicKey="ARRIVAL_NOTIFICATION"
                  count={ev.arrival_notification} queueSize={q.arrival_notification} accent="#e67e22" />
              </div>
            </div>
          </div>

          {/* Dotted connector from Entry Broker to Arrival Notification lane */}
          <FanOutSVG height={totalH} targetYs={[yc2]} width={48} color="#e67e22" dashed />

          {/* Col 4: RT Score + OV fan-in to routing section */}
          <FanInSVG height={totalH} inputYs={[yc0, yc1, yc2]} outputY={totalH / 2} width={48} />

          {/* Col 5: Three routing outputs — Green / Red / Amber */}
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', height: totalH }}>
            <Zone label="Risk Routing" style={{ height: routeTotalH }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: routeGap }}>

                {/* GREEN path */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: routeRowH }}>
                  <FactoryNode icon="🟢" label="Release Factory" description="validation+green+arrival" accent="#1f7a3c" />
                  <Arrow color="#1f7a3c" />
                  <BrokerNode label="Release Event" topicKey="RELEASE_EVENT"
                    count={ev.release_event} queueSize={q.release_event} accent="#1f7a3c" />
                  <Arrow color="#1f7a3c" label="→ DB" />
                </div>

                {/* RED path */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: routeRowH }}>
                  <FactoryNode icon="🔴" label="Retain Factory" description="red score only" accent="#c0392b" />
                  <Arrow color="#c0392b" />
                  <BrokerNode label="Retain Event" topicKey="RETAIN_EVENT"
                    count={ev.retain_event} queueSize={q.retain_event} accent="#c0392b" />
                  <Arrow color="#c0392b" label="→ DB" />
                </div>

                {/* AMBER path */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: routeRowH }}>
                  <FactoryNode icon="🟡" label="Investigate Dispatch" description="amber+validation" accent="#e6820a" />
                  <Arrow color="#e6820a" />
                  <BrokerNode label="Investigate Event" topicKey="INVESTIGATE_EVENT"
                    count={ev.investigate_event} queueSize={q.investigate_event} accent="#e6820a" />
                  <Arrow color="#e6820a" label="↓ inv." />
                </div>

              </div>
            </Zone>
          </div>

          {/* Col 6: DB Sink — receives green and red releases */}
          <div style={{ height: totalH, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <Zone label="Sink">
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                <FactoryNode icon="💾" label="DB Store Worker" description="Insert + flag suspicious" />
                <Arrow down />
                <DBSinkNode count={stored} />
              </div>
            </Zone>
          </div>

        </div>
      </div>

      {/* ── INVESTIGATION SUB-PIPELINE ── */}
      <div style={{ margin: '0 20px 4px', padding: '12px 14px', background: '#fdf6ff', border: '1.5px solid #9c27b066', borderRadius: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#7b1fa2', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12 }}>
          Investigation Sub-Pipeline (AMBER / Ireland)
        </div>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 0, minWidth: 'max-content' }}>

            {/* From INVESTIGATE_EVENT → Investigator Factory */}
            <FactoryNode icon="🕵️" label="Investigator Factory" description="IE-filter · FIFO queue" accent="#9c27b0" />
            <Arrow color="#9c27b0" />

            {/* Investigation Queue */}
            <QueueNode label="Investigation Queue" count={inv} accent="#9c27b0" />
            <Arrow color="#9c27b0" />

            {/* VAT Agent Worker */}
            <FactoryNode icon="🤖" label="VAT Agent Worker" description="LM Studio · fraud detection" accent="#9c27b0" />

            {/* Agent fork: incorrect → retain / correct → release */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8, marginLeft: 8 }}>

              {/* Incorrect → retain */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Arrow color="#c0392b" />
                <BrokerNode label="Retained after Investigation" topicKey="AGENT_RETAIN_EVENT"
                  count={ev.agent_retain_event} queueSize={q.agent_retain_event} accent="#c0392b" />
                <Arrow color="#c0392b" label="→ DB" />
              </div>

              {/* Correct/uncertain → release path */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Arrow color="#1f7a3c" />
                <BrokerNode label="To Be Released after Inv." topicKey="AGENT_RELEASE_EVENT"
                  count={ev.agent_release_event} queueSize={q.agent_release_event} accent="#1f7a3c" />
                <Arrow color="#1f7a3c" />
                <FactoryNode icon="🔓" label="Release After Inv. Factory" description="agent-release + OV + arrival" accent="#1f7a3c" />
                <Arrow color="#1f7a3c" />
                <BrokerNode label="Release After Investigation" topicKey="RELEASE_AFTER_INVESTIGATION_EVENT"
                  count={ev.release_after_investigation_event}
                  queueSize={q.release_after_investigation_event} accent="#1f7a3c" />
                <Arrow color="#1f7a3c" label="→ DB" />
              </div>
            </div>

          </div>
        </div>
      </div>

      {/* Legend */}
      <div style={{ padding: '10px 20px 16px', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', borderTop: '1px solid var(--border-light)' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)' }}>Legend:</span>
        <LegendItem color="var(--eu-blue)" bg="var(--eu-blue-light)" label="Broker (solid)" />
        <LegendItem color="var(--border)" bg="#f8f9fa" label="Factory" />
        <LegendItem color="#1f7a3c" bg="#e8f5e9" label="GREEN — release" />
        <LegendItem color="#c0392b" bg="#fde8e8" label="RED — retain" />
        <LegendItem color="#e6820a" bg="#fff3e0" label="AMBER — investigate" />
        <LegendItem color="#9c27b0" bg="#fdf6ff" label="Investigation pipeline" />
        <LegendItem color="#e67e22" bg="#fff8f0" label="Arrival Notification (dashed)" dashed />
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
