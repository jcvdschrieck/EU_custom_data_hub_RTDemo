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

// ── Helpers ───────────────────────────────────────────────────────────────────

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

        {/* Status row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className={`sim-dot ${dotClass}`} style={{ width: 12, height: 12 }} />
            <span style={{ fontSize: 17, fontWeight: 700, color: stateColor }}>{stateLabel}</span>
          </div>
          <StatChip label="Sim date"    value={sim_time ? sim_time.slice(0, 10) : '—'} />
          <StatChip label="Fired"       value={`${fmt(fired_count)} / ${fmt(total)}`} />
          <StatChip label="Completion"  value={`${(pct_complete || 0).toFixed(1)}%`} />
          <StatChip
            label="Active alarms"
            value={fmt(active_alarms)}
            accent={active_alarms > 0 ? 'var(--error)' : null}
          />
        </div>

        {/* Progress bar */}
        <div style={{
          height: 10, background: '#e9ecef', borderRadius: 5,
          marginBottom: 20, overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${pct_complete || 0}%`,
            background: finished ? '#adb5bd' : running ? 'var(--eu-blue)' : 'var(--warning)',
            transition: 'width 0.6s ease',
            borderRadius: 5,
          }} />
        </div>

        {/* Buttons + speed */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            onClick={handleToggle}
            disabled={finished || busy}
            style={{
              background: running ? '#e9ecef' : 'var(--eu-blue)',
              color: running ? 'var(--text-primary)' : '#fff',
              border: 'none', borderRadius: 'var(--radius)',
              padding: '8px 22px', fontSize: 13, fontWeight: 700,
              cursor: finished || busy ? 'not-allowed' : 'pointer',
              minWidth: 110,
            }}
          >
            {running ? '⏸ Pause' : fired_count ? '▶ Resume' : '▶ Start'}
          </button>

          <button
            onClick={() => act(simReset)}
            disabled={busy}
            style={{
              background: '#f8f9fa', color: 'var(--text-primary)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              padding: '8px 16px', fontSize: 13, fontWeight: 600,
              cursor: busy ? 'not-allowed' : 'pointer',
            }}
          >
            ↺ Reset
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 12 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>Speed:</span>
            {SPEEDS.map(s => (
              <button
                key={s.value}
                onClick={() => act(() => simSetSpeed(s.value))}
                disabled={busy}
                style={{
                  background: speed === s.value ? 'var(--eu-blue)' : '#f8f9fa',
                  color: speed === s.value ? '#fff' : 'var(--text-primary)',
                  border: `1px solid ${speed === s.value ? 'var(--eu-blue)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius)',
                  padding: '5px 11px', fontSize: 12, fontWeight: 600,
                  cursor: busy ? 'not-allowed' : 'pointer',
                }}
              >
                {s.label}
              </button>
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

// ── Pipeline node components ──────────────────────────────────────────────────

function BrokerNode({ label, topicKey, count, queueSize, children }) {
  return (
    <div style={{
      background: 'var(--eu-blue-light)',
      border: '2px solid var(--eu-blue)',
      borderRadius: 'var(--radius)',
      padding: '10px 14px',
      minWidth: 148,
      textAlign: 'center',
      flex: '0 0 auto',
    }}>
      <div style={{
        fontSize: 9, color: 'var(--eu-blue)', textTransform: 'uppercase',
        letterSpacing: '0.07em', marginBottom: 4, fontWeight: 700,
      }}>
        {topicKey}
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6, lineHeight: 1.3 }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--eu-blue)', lineHeight: 1 }}>
        {fmt(count)}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>events persisted</div>
      {queueSize > 0 && (
        <div style={{
          marginTop: 5, fontSize: 10, color: 'var(--warning)', fontWeight: 700,
          background: '#fff8e6', borderRadius: 8, padding: '1px 6px', display: 'inline-block',
        }}>
          {queueSize} in queue
        </div>
      )}
      {children}
    </div>
  )
}

function FactoryNode({ label, description, icon }) {
  return (
    <div style={{
      background: '#f8f9fa',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: '8px 12px',
      minWidth: 138,
      textAlign: 'center',
      flex: '0 0 auto',
    }}>
      <div style={{ fontSize: 18, marginBottom: 3 }}>{icon}</div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>{label}</div>
      {description && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>{description}</div>
      )}
    </div>
  )
}

function SourceSinkNode({ icon, title, label, count, suffix, color = 'var(--success)' }) {
  return (
    <div style={{
      background: color === 'var(--success)' ? '#e8f5e9' : '#e8f0fe',
      border: `2px solid ${color}`,
      borderRadius: 'var(--radius)',
      padding: '10px 14px',
      minWidth: 130,
      textAlign: 'center',
      flex: '0 0 auto',
    }}>
      <div style={{ fontSize: 18, marginBottom: 3 }}>{icon}</div>
      <div style={{ fontSize: 9, color, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 700, marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6, lineHeight: 1.3 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color, lineHeight: 1 }}>{fmt(count)}</div>
      {suffix && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{suffix}</div>}
    </div>
  )
}

function Arrow({ label, down = false }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', gap: 3, padding: down ? '2px 0' : '0 6px', flex: '0 0 auto',
    }}>
      {down ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ width: 2, height: 18, background: '#adb5bd' }} />
          <div style={{ width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: '7px solid #adb5bd' }} />
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ width: 22, height: 2, background: '#adb5bd' }} />
          <div style={{ width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderLeft: '7px solid #adb5bd' }} />
        </div>
      )}
      {label && <div style={{ fontSize: 9, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{label}</div>}
    </div>
  )
}

/**
 * FanOutSVG — draws a vertical spine with N branching arrows pointing right.
 * yc: array of y-positions for each branch (relative to SVG top).
 * Only the rows listed in targetYs get an arrow; spine spans first→last.
 */
function FanOutSVG({ height, targetYs, color = '#adb5bd', width = 52 }) {
  if (!targetYs || targetYs.length < 1) return null
  const spineX = 8
  const y0 = targetYs[0]
  const y1 = targetYs[targetYs.length - 1]
  return (
    <svg width={width} height={height} style={{ flex: `0 0 ${width}px`, overflow: 'visible' }}>
      {/* vertical spine */}
      <line x1={spineX} y1={y0} x2={spineX} y2={y1} stroke={color} strokeWidth={2} />
      {targetYs.map((yc, i) => (
        <g key={i}>
          <circle cx={spineX} cy={yc} r={3.5} fill={color} />
          <line x1={spineX} y1={yc} x2={width - 8} y2={yc} stroke={color} strokeWidth={2} />
          <polygon points={`${width-8},${yc-4} ${width},${yc} ${width-8},${yc+4}`} fill={color} />
        </g>
      ))}
    </svg>
  )
}

/**
 * FanInSVG — draws N horizontal input lines converging to a vertical spine,
 * then a single output arrow pointing right from the spine midpoint.
 */
function FanInSVG({ height, inputYs, outputY, color = '#adb5bd', width = 52 }) {
  if (!inputYs || inputYs.length < 1) return null
  const spineX = width - 8
  const y0 = inputYs[0]
  const y1 = inputYs[inputYs.length - 1]
  return (
    <svg width={width} height={height} style={{ flex: `0 0 ${width}px`, overflow: 'visible' }}>
      {/* vertical spine */}
      <line x1={spineX} y1={y0} x2={spineX} y2={y1} stroke={color} strokeWidth={2} />
      {inputYs.map((yc, i) => (
        <g key={i}>
          <line x1={0} y1={yc} x2={spineX} y2={yc} stroke={color} strokeWidth={2} />
          <circle cx={spineX} cy={yc} r={3.5} fill={color} />
        </g>
      ))}
      {/* output arrow from spine midpoint */}
      <line x1={spineX} y1={outputY} x2={spineX + 1} y2={outputY} stroke={color} strokeWidth={2} />
      <polygon points={`${spineX},${outputY-4} ${width},${outputY} ${spineX},${outputY+4}`} fill={color} />
    </svg>
  )
}

function ZoneLabel({ children }) {
  return (
    <div style={{
      fontSize: 9, fontWeight: 700, color: 'var(--text-muted)',
      textTransform: 'uppercase', letterSpacing: '0.08em',
      textAlign: 'center', marginBottom: 8,
    }}>
      {children}
    </div>
  )
}

function Zone({ label, children, style }) {
  return (
    <div style={{
      border: '1px dashed var(--border-light)',
      borderRadius: 6,
      padding: '10px 12px',
      flex: '0 0 auto',
      ...style,
    }}>
      {label && <ZoneLabel>{label}</ZoneLabel>}
      {children}
    </div>
  )
}

// ── Pipeline diagram ──────────────────────────────────────────────────────────

function FlaggedBadge({ flagged, total }) {
  if (total == null || total === 0) return null
  const pct = ((flagged ?? 0) / total * 100).toFixed(0)
  return (
    <div style={{ marginTop: 6, display: 'flex', justifyContent: 'center', gap: 4 }}>
      <span style={{ background: '#fde8e8', color: 'var(--error)', border: '1px solid #f5c6cb', padding: '1px 7px', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>
        ⚑ {fmt(flagged)} flagged ({pct}%)
      </span>
    </div>
  )
}

function ScoreBadges({ green, amber, red }) {
  if (green == null && amber == null && red == null) return null
  return (
    <div style={{ marginTop: 6, display: 'flex', justifyContent: 'center', gap: 3, flexWrap: 'wrap' }}>
      <span style={{ background: '#d4edda', color: '#155724', border: '1px solid #c3e6cb', padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>● {fmt(green)}</span>
      <span style={{ background: '#fff3cd', color: '#856404', border: '1px solid #ffc107', padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>● {fmt(amber)}</span>
      <span style={{ background: '#fde8e8', color: '#c0392b', border: '1px solid #f5c6cb', padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>● {fmt(red)}</span>
    </div>
  )
}

function PipelineDiagram({ pipeline, status }) {
  const ev     = pipeline?.events     || {}
  const q      = pipeline?.queues     || {}
  const rf     = pipeline?.risk_flags || {}
  const stored = pipeline?.stored_count ?? null

  const GAP = 16

  // Measure actual rendered row heights so SVG connectors align perfectly
  const row0Ref = useRef(null)
  const row1Ref = useRef(null)
  const row2Ref = useRef(null)
  const [rowH, setRowH] = useState([90, 190, 90])

  useEffect(() => {
    const h = [
      row0Ref.current?.offsetHeight ?? 90,
      row1Ref.current?.offsetHeight ?? 190,
      row2Ref.current?.offsetHeight ?? 90,
    ]
    setRowH(prev => h.every((v, i) => v === prev[i]) ? prev : h)
  })

  const [h0, h1, h2] = rowH
  const h01     = h0 + GAP + h1
  const totalH  = h0 + GAP + h1 + GAP + h2

  // y-center of each lane row within the lanes column (from top = 0)
  const yc0 = h0 / 2
  const yc1 = h0 + GAP + h1 / 2
  const yc2 = h0 + GAP + h1 + GAP + h2 / 2

  const laneBox = (accent) => ({
    border: `2px solid ${accent}`,
    borderRadius: 6,
    padding: '10px 12px',
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  })

  return (
    <div className="card section-gap">
      <div className="card-header">
        Pipeline Flow
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
          event counts auto-refresh every 3 s
        </span>
      </div>

      <div style={{ overflowX: 'auto', padding: '24px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', minWidth: 'max-content' }}>

          {/* ── Col 1: Entry Broker — vertically centered over rows 0+1 ── */}
          <div style={{ height: totalH, display: 'flex', flexDirection: 'column', justifyContent: 'flex-start' }}>
            <div style={{ height: h01, display: 'flex', alignItems: 'center' }}>
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

          {/* ── Col 2: Fan-out SVG — two branches to OV and RT Risk ────── */}
          <FanOutSVG
            height={totalH}
            targetYs={[yc0, yc1]}
            width={52}
          />

          {/* ── Col 3: Three parallel lanes ─────────────────────────────── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>

            {/* Lane A: Order Validation */}
            <div ref={row0Ref}>
              <ZoneLabel>Order Validation</ZoneLabel>
              <div style={laneBox('#1f7a3c')}>
                <FactoryNode icon="✅" label="Order Validation" description="Field completeness" />
                <Arrow />
                <BrokerNode
                  label="Order Validation"
                  topicKey="ORDER_VALIDATION"
                  count={ev.order_validation}
                  queueSize={q.order_validation}
                />
              </div>
            </div>

            {/* Lane B: RT Risk Monitoring */}
            <div ref={row1Ref}>
              <ZoneLabel>RT Risk Monitoring</ZoneLabel>
              <div style={laneBox('#6f42c1')}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <FactoryNode icon="⚖️" label="RT Risk Monitoring 1" description="VAT ratio deviation" />
                    <Arrow />
                    <BrokerNode
                      label="RT Risk 1 Outcome"
                      topicKey="RT_RISK_1_OUTCOME"
                      count={ev.rt_risk_1_outcome}
                      queueSize={q.rt_risk_1_outcome}
                    >
                      <FlaggedBadge flagged={rf.rt_risk_1_flagged} total={ev.rt_risk_1_outcome} />
                    </BrokerNode>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <FactoryNode icon="🔍" label="RT Risk Monitoring 2" description="Watchlist lookup" />
                    <Arrow />
                    <BrokerNode
                      label="RT Risk 2 Outcome"
                      topicKey="RT_RISK_2_OUTCOME"
                      count={ev.rt_risk_2_outcome}
                      queueSize={q.rt_risk_2_outcome}
                    >
                      <FlaggedBadge flagged={rf.rt_risk_2_flagged} total={ev.rt_risk_2_outcome} />
                    </BrokerNode>
                  </div>
                </div>
                <Arrow label="merge" />
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <FactoryNode icon="🔄" label="RT Consolidation Factory" description="GREEN / AMBER / RED" />
                  <Arrow down />
                  <BrokerNode
                    label="RT Score"
                    topicKey="RT_SCORE"
                    count={ev.rt_score}
                    queueSize={q.rt_score}
                  >
                    <ScoreBadges green={rf.rt_score_green} amber={rf.rt_score_amber} red={rf.rt_score_red} />
                  </BrokerNode>
                </div>
              </div>
            </div>

            {/* Lane C: Arrival Notification — standalone, no arrow from Entry Broker */}
            <div ref={row2Ref}>
              <ZoneLabel>Arrival Notification</ZoneLabel>
              <div style={laneBox('#e67e22')}>
                <BrokerNode
                  label="Arrival Notification Broker"
                  topicKey="ARRIVAL_NOTIFICATION"
                  count={ev.arrival_notification}
                  queueSize={q.arrival_notification}
                />
              </div>
            </div>

          </div>

          {/* ── Col 4: Fan-in SVG — three inputs converge to Release ────── */}
          <FanInSVG
            height={totalH}
            inputYs={[yc0, yc1, yc2]}
            outputY={totalH / 2}
            width={52}
          />

          {/* ── Col 5: Release + Sink — vertically centered ──────────────── */}
          <div style={{ height: totalH, display: 'flex', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>

              <Zone label="Release">
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <FactoryNode icon="🚀" label="Release Factory" description="Score + Validation + Arrival" />
                  <Arrow down />
                  <BrokerNode
                    label="Release Event"
                    topicKey="RELEASE_EVENT"
                    count={ev.release_event}
                    queueSize={q.release_event}
                  />
                </div>
              </Zone>

              <Arrow label="store" />

              <Zone label="Sink">
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <FactoryNode icon="💾" label="DB Store Factory" description="Insert + flag suspicious" />
                  <Arrow down />
                  <SourceSinkNode
                    icon="🏛️"
                    title="Custom Data Hub"
                    label="Stored transactions"
                    count={stored}
                    suffix="records stored"
                    color="var(--eu-blue)"
                  />
                </div>
              </Zone>

            </div>
          </div>

        </div>
      </div>

      {/* Legend */}
      <div style={{
        padding: '10px 20px 16px',
        display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center',
        borderTop: '1px solid var(--border-light)',
      }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)' }}>Legend:</span>
        <LegendItem color="var(--eu-blue)" bg="var(--eu-blue-light)" label="Broker" />
        <LegendItem color="var(--border)" bg="#f8f9fa" label="Factory" />
        <LegendItem color="#1f7a3c" bg="#e8f5e9" label="Order Validation lane" />
        <LegendItem color="#6f42c1" bg="#f3eeff" label="RT Risk Monitoring lane" />
        <LegendItem color="#e67e22" bg="#fff3e0" label="Arrival Notification lane" />
        <div style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
          Counts reflect JSON events persisted to <code>data/events/</code> since last reset.
        </div>
      </div>
    </div>
  )
}

function LegendItem({ color, bg, label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{
        width: 14, height: 14,
        background: bg, border: `2px solid ${color}`,
        borderRadius: 2,
      }} />
      <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{label}</span>
    </div>
  )
}

// ── Event counts table ────────────────────────────────────────────────────────

const TOPIC_META = [
  { key: 'sales_order_event',    label: 'Sales-order Event Broker',    factory: 'Simulation loop',             color: '#0050a0' },
  { key: 'order_validation',     label: 'Order Validation',            factory: 'Order Validation Factory',    color: '#1f7a3c' },
  { key: 'rt_risk_1_outcome',    label: 'RT Risk 1 Outcome',           factory: 'RT Risk Monitoring 1',        color: '#6f42c1' },
  { key: 'rt_risk_2_outcome',    label: 'RT Risk 2 Outcome',           factory: 'RT Risk Monitoring 2',        color: '#6f42c1' },
  { key: 'rt_score',             label: 'RT Score',                    factory: 'RT Consolidation Factory',    color: '#e6820a' },
  { key: 'arrival_notification', label: 'Arrival Notification',        factory: 'Arrival Notification Factory', color: '#e67e22' },
  { key: 'release_event',        label: 'Release Event',               factory: 'Release Factory',             color: '#c0392b' },
]

function EventCountsTable({ pipeline }) {
  const ev = pipeline?.events || {}
  const q  = pipeline?.queues || {}
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
              const pct = total > 0 ? (count / total * 100) : 0
              return (
                <tr key={t.key}>
                  <td>
                    <span style={{
                      background: t.color + '18', color: t.color,
                      border: `1px solid ${t.color}40`,
                      padding: '2px 8px', borderRadius: 8,
                      fontSize: 11, fontWeight: 700,
                    }}>
                      {t.key}
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>{t.factory}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(count)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {queue > 0
                      ? <span style={{ color: 'var(--warning)', fontWeight: 700 }}>{queue}</span>
                      : <span style={{ color: 'var(--text-muted)' }}>0</span>
                    }
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

  const refreshStatus = useCallback(async () => {
    try { setStatus(await getSimStatus()) } catch { /* not ready */ }
  }, [])

  const refreshPipeline = useCallback(async () => {
    try { setPipeline(await getPipelineStats()) } catch { /* not ready */ }
  }, [])

  // Status: every 2 s
  useEffect(() => {
    refreshStatus()
    const id = setInterval(refreshStatus, 2000)
    return () => clearInterval(id)
  }, [refreshStatus])

  // Pipeline counts: every 3 s
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
