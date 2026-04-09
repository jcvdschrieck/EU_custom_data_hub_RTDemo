import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getSimStatus, getPipelineStats, openSimStateStream,
  simStart, simPause, simResume, simReset, simSetSpeed,
} from '../api'

// User-facing speed multipliers. The simulation DB is rescaled at seed time
// so all transactions fall within a 15-sim-minute window (March 1st 00:00 →
// 00:15). The `value` sent to the backend is sim-seconds per real-second, so
// ×1 = real-time playback (15 sim-min in 15 real-min).
//   ×1   →   1 sim-sec/real-sec → 15 sim-min in 15 real-min  (default)
//   ×10  →  10 sim-sec/real-sec → 15 sim-min in  1.5 real-min
//   ×100 → 100 sim-sec/real-sec → 15 sim-min in   ~9 real-sec
const SPEEDS = [
  { label: '×1',   value: 1   },
  { label: '×10',  value: 10  },
  { label: '×100', value: 100 },
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
          <StatChip label="Sim time"    value={sim_time ? sim_time.slice(0, 19).replace('T', ' ') : '—'} />
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

// Solid light backgrounds for broker sub-boxes — mirror the ScoreBadges
// palette (opaque colors, no alpha) so the sub-box doesn't pick up the parent
// blue background through transparency.
const BROKER_SUB_BG = {
  '#1f7a3c': '#e8f5e9',  // green  → light green
  '#c0392b': '#fde8e8',  // red    → light red
  '#e6820a': '#fff3e0',  // orange → light amber
}

function BrokerNode({ label, topicKey, count, children, accent, sm, tooltip, width }) {
  // Outer border is ALWAYS the EU blue "broker" color so all brokers read as
  // the same element type. When an accent is provided (e.g. green for release,
  // red for retain, orange for investigate), it moves to an inner sub-box that
  // wraps the label and count — differentiating the broker's content type
  // without breaking the "all brokers are blue" visual rule.
  const blue = 'var(--eu-blue)'
  const hasAccent = !!accent
  const innerColor = accent || blue
  const innerBg    = hasAccent ? (BROKER_SUB_BG[accent] || '#ffffff') : '#ffffff'
  const defaultMinW = sm ? 100 : 130
  return (
    <div
      title={tooltip}
      style={{
        background: 'var(--eu-blue-light)',
        border: `2px solid ${blue}`,
        borderRadius: 'var(--radius)',
        padding: sm ? '3px 5px 4px' : '5px 7px 6px',
        width: width || undefined,
        minWidth: width || defaultMinW,
        textAlign: 'center', flex: '0 0 auto',
        cursor: tooltip ? 'help' : 'default',
        boxSizing: 'border-box',
      }}>
      {/* Outer: topic key header */}
      <div style={{
        fontSize: 7, color: blue, textTransform: 'uppercase',
        letterSpacing: '0.06em', marginBottom: 3, fontWeight: 700,
      }}>{topicKey}</div>

      {/* Inner sub-box: label + count + "events", colored by accent (if any) */}
      <div style={{
        background: innerBg,
        border: `1.5px solid ${innerColor}`,
        borderRadius: 3,
        padding: sm ? '2px 4px 3px' : '3px 6px 4px',
      }}>
        <div style={{
          fontSize: sm ? 9 : 10, fontWeight: 700,
          color: 'var(--text-primary)',
          lineHeight: 1.2, marginBottom: 1,
        }}>{label}</div>
        <div style={{
          fontSize: sm ? 15 : 18, fontWeight: 700,
          color: innerColor, lineHeight: 1,
        }}>{fmt(count)}</div>
        <div style={{
          fontSize: 7, color: 'var(--text-muted)',
          marginTop: 1, lineHeight: 1,
        }}>events</div>
      </div>

      {children}
    </div>
  )
}

function FactoryNode({ label, description, icon, accent, sm, tooltip, width }) {
  const defaultMinW = sm ? 86 : 120
  return (
    <div
      title={tooltip}
      style={{
        background: accent ? accent + '12' : '#f8f9fa',
        border: `1px solid ${accent || 'var(--border)'}`,
        borderRadius: 8, padding: sm ? '4px 7px' : '6px 10px',
        width: width || undefined,
        minWidth: width || defaultMinW,
        textAlign: 'center', flex: '0 0 auto',
        cursor: tooltip ? 'help' : 'default',
        boxSizing: 'border-box',
      }}>
      <div style={{ fontSize: sm ? 13 : 15, marginBottom: 2 }}>{icon}</div>
      <div style={{ fontSize: sm ? 9 : 10, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>{label}</div>
      {description && <div style={{ fontSize: 8, color: 'var(--text-muted)', marginTop: 1 }}>{description}</div>}
    </div>
  )
}

function QueueNode({ label, count, accent, tooltip, sm }) {
  // Default palette: gray, slightly darker than FactoryNode so the queue still
  // reads as "processing-ish" but clearly in the factory family (not a broker).
  // Caller can still pass `accent` to override (used if a colored queue is
  // needed somewhere else in the future).
  const borderColor = accent || '#868e96'             // gray-500 (darker than factory border #c8c8c8)
  const bgColor     = accent ? accent + '15' : '#eceff1' // light gray bg (darker than factory #f8f9fa)
  const textColor   = accent || '#495057'             // gray-700
  return (
    <div
      title={tooltip}
      style={{
        background: bgColor,
        border: `2px dashed ${borderColor}`,
        borderRadius: 'var(--radius)',
        padding: sm ? '3px 10px 4px' : '8px 12px',
        minWidth: sm ? 120 : 130, textAlign: 'center', flex: '0 0 auto',
        cursor: tooltip ? 'help' : 'default',
      }}>
      <div style={{ fontSize: sm ? 11 : 14, marginBottom: sm ? 0 : 2, lineHeight: 1 }}>📋</div>
      <div style={{ fontSize: sm ? 9 : 10, fontWeight: 700, color: textColor, lineHeight: 1.2 }}>{label}</div>
      {count != null && (
        <div style={{ fontSize: sm ? 14 : 18, fontWeight: 700, color: textColor, marginTop: sm ? 1 : 3, lineHeight: 1 }}>{fmt(count)}</div>
      )}
      <div style={{ fontSize: sm ? 7 : 9, color: 'var(--text-muted)', marginTop: sm ? 0 : 1, lineHeight: 1.2 }}>FIFO queue</div>
    </div>
  )
}

// Database cylinder — visually distinct from brokers and factories.
// Uses a sky-blue scheme (clearly a different shade from the dark EU event-
// broker blue #003399) and an SVG cylinder icon so it reads as
// "this is a persistent data store", not another event broker.
function DBSinkNode({ count, newCount, tooltip }) {
  const dbMain  = '#0284c7'   // sky blue 600
  const dbDark  = '#075985'   // sky blue 800
  const dbCap   = '#38bdf8'   // sky blue 400 (top cap highlight)
  const dbLight = '#e0f2fe'   // sky blue 50
  return (
    <div
      title={tooltip}
      style={{
        position: 'relative',
        background: dbLight,
        border: `2px solid ${dbMain}`,
        borderRadius: 10,
        padding: '8px 14px 10px',
        minWidth: 150, textAlign: 'center', flex: '0 0 auto',
        cursor: tooltip ? 'help' : 'default',
        boxShadow: '0 1px 4px rgba(2, 132, 199, 0.18)',
      }}>
      {/* Cylinder icon — stylised DB shape */}
      <svg width={30} height={24} viewBox="0 0 30 24" style={{ display: 'block', margin: '0 auto 2px' }}>
        {/* bottom ellipse (back) */}
        <ellipse cx={15} cy={20} rx={12} ry={3} fill={dbDark} />
        {/* body */}
        <rect x={3} y={4} width={24} height={16} fill={dbMain} />
        {/* disk separator lines (subtle) */}
        <ellipse cx={15} cy={9}  rx={12} ry={3} fill="none" stroke={dbDark} strokeWidth={0.5} opacity={0.45} />
        <ellipse cx={15} cy={14} rx={12} ry={3} fill="none" stroke={dbDark} strokeWidth={0.5} opacity={0.45} />
        {/* top ellipse (visible cap) */}
        <ellipse cx={15} cy={4}  rx={12} ry={3} fill={dbCap} stroke={dbDark} strokeWidth={0.7} />
      </svg>
      <div style={{
        fontSize: 9, color: dbDark,
        textTransform: 'uppercase', letterSpacing: '0.08em',
        fontWeight: 700, marginBottom: 2,
      }}>Custom Data Hub</div>
      <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4, lineHeight: 1.2 }}>
        MongoDB · Stored transactions
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: dbDark, lineHeight: 1 }}>
        {fmt(count)}
      </div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>records total</div>
      {newCount > 0 && (
        <div style={{
          marginTop: 4, fontSize: 10, fontWeight: 700, color: '#1f7a3c',
          background: '#e8f5e9', border: '1px solid #1f7a3c88',
          borderRadius: 10, padding: '1px 8px', display: 'inline-block',
        }}>
          +{fmt(newCount)} new
        </div>
      )}
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

function LongArrow({ color = '#adb5bd', width = 160 }) {
  return (
    <svg width={width} height={10} style={{ flex: `0 0 ${width}px`, display: 'block' }}>
      <line x1={0} y1={5} x2={width - 6} y2={5} stroke={color} strokeWidth={2} />
      <polygon points={`${width-6},1 ${width},5 ${width-6},9`} fill={color} />
    </svg>
  )
}

function ZoneLabel({ children, color }) {
  return (
    <div style={{
      fontSize: 9, fontWeight: 700, color: color || 'var(--text-muted)',
      textTransform: 'uppercase', letterSpacing: '0.08em',
      textAlign: 'center', marginBottom: 6,
      position: 'sticky', top: 0, zIndex: 2,
      background: '#fff', padding: '2px 4px',
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

// Curved-up arrow used to indicate "goes to DB Store Factory above" without
// drawing an arrow that physically crosses into the routing row container.
function CurveUpArrow({ color = '#adb5bd', label, width = 48, height = 40 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, flex: '0 0 auto' }}>
      <svg width={width} height={height} style={{ overflow: 'visible' }}>
        <path
          d={`M 4 ${height - 4} Q 4 4 ${width - 10} 4`}
          stroke={color} strokeWidth={2} fill="none" strokeLinecap="round"
        />
        <polygon points={`${width-10},0 ${width-2},4 ${width-10},8`} fill={color} />
      </svg>
      {label && (
        <div style={{ fontSize: 8, color, fontWeight: 700, whiteSpace: 'nowrap' }}>{label}</div>
      )}
    </div>
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

// ── Middle section: DB Store + Hub (grouped in a dashed zone) + after-Inv
// brokers (mirroring event brokers) + inline investigation pipeline ──────────
//
// An absolute-positioned canvas that holds the second half of the pipeline on
// a single literal row. Release / Retain / Investigate events arrive from the
// left edge (x=0) at Y levels matching the parent flow (passed as props).
//
// DB Store Factory and the Custom Data Hub cylinder are wrapped in a single
// dashed zone — incoming arrows terminate at the zone's outer border rather
// than the individual elements, like Order Validation / RT Risk / Transport
// zones on the left.
//
// Loop-back arrows:
//   Post-Inv Release → Release-after-Inv  (green, bottom → top)
//   VAT Agent        → Retained-after-Inv (red, "incorrect" branch)
// Vertical legs are routed OUTSIDE the after-Inv broker x range so the lines
// don't pass through the box interiors.
function MiddleSection({ ev, rf, inv, stored, newStored, H, yRel, yRet, yInv }) {
  const Y_REL = yRel
  const Y_RET = yRet
  const Y_INV = yInv

  // Incoming-arrow runway on the left edge
  const IN_ARROW_W = 60

  // ── DB Store · Hub group (dashed zone) ───────────────────────────────────
  // The zone must contain Y_REL and Y_RET so horizontal arrows can terminate
  // at its left/right borders at those Y values.
  const ZONE_LEFT   = IN_ARROW_W
  const ZONE_W      = 210
  const ZONE_TOP    = 10                       // above Y_REL so border sits above it
  const ZONE_H      = Y_RET + 90 - ZONE_TOP    // extends well below Y_RET
  const ZONE_RIGHT  = ZONE_LEFT + ZONE_W       // 270
  const ZONE_BOTTOM = ZONE_TOP + ZONE_H

  // ── After-Inv brokers (mirror Release / Retain event brokers) ────────────
  const AFT_W = 150
  const AFT_H = 78
  const AFT_LEFT   = ZONE_RIGHT + 56          // 326
  const AFT_RIGHT  = AFT_LEFT + AFT_W         // 476
  const RAFT_TOP   = Y_REL - AFT_H / 2
  const RETAFT_TOP = Y_RET - AFT_H / 2

  // ── Investigation pipeline at Y_INV (bottom band) ────────────────────────
  const INV_ROW_CY   = Y_INV                   // vertical center of investigation elements
  const INVFACT_W    = 130
  const INVFACT_LEFT = IN_ARROW_W
  const QUEUE_W      = 134
  const QUEUE_LEFT   = INVFACT_LEFT + INVFACT_W + 22
  const AGENT_W      = 140
  const AGENT_LEFT   = QUEUE_LEFT + QUEUE_W + 22
  const AGENT_RIGHT  = AGENT_LEFT + AGENT_W
  const CLRREL_W     = 126
  const CLRREL_LEFT  = AGENT_RIGHT + 28
  const POSTINV_W    = 158
  const POSTINV_LEFT = CLRREL_LEFT + CLRREL_W + 24
  const POSTINV_RIGHT = POSTINV_LEFT + POSTINV_W

  // Total canvas width — leaves room on the right for the Post-Inv loop-back column
  const W = POSTINV_RIGHT + 48

  // Approximate factory/broker heights for Y alignment on the bottom band
  const INV_FACT_H = 56
  const INV_ROW_TOP = INV_ROW_CY - INV_FACT_H / 2

  // ── Loop-back routing ────────────────────────────────────────────────────
  // Vertical legs MUST lie outside the after-Inv broker x range [AFT_LEFT, AFT_RIGHT]
  // so they don't cross the broker interiors.
  //
  // Post-Inv Release → Release-after-Inv: vertical at POSTINV_CX (>> AFT_RIGHT)
  const POSTINV_CX = POSTINV_LEFT + POSTINV_W / 2
  // Agent → Retained-after-Inv (incorrect): vertical at AFT_RIGHT + margin, which
  // is inside the Agent's x range so the exit point is on the Agent's top edge.
  const RETAIN_UP_X = AFT_RIGHT + 20          // 496, inside Agent x range (AGENT_LEFT..AGENT_RIGHT)

  const stroke = 2
  const grey   = '#adb5bd'
  const green  = '#1f7a3c'
  const red    = '#c0392b'
  const orange = '#e6820a'
  const purple = '#9c27b0'

  // Small helper for arrowheads at a point, given direction
  const Arrowhead = ({ x, y, dir, color }) => {
    const s = 6
    let pts
    if      (dir === 'right') pts = `${x-s},${y-s} ${x},${y} ${x-s},${y+s}`
    else if (dir === 'left')  pts = `${x+s},${y-s} ${x},${y} ${x+s},${y+s}`
    else if (dir === 'down')  pts = `${x-s},${y-s} ${x},${y} ${x+s},${y-s}`
    else                      pts = `${x-s},${y+s} ${x},${y} ${x+s},${y+s}`
    return <polygon points={pts} fill={color} />
  }

  return (
    <div style={{ position: 'relative', width: W, height: H, flexShrink: 0 }}>
      {/* Arrow/connector overlay */}
      <svg style={{ position: 'absolute', top: 0, left: 0, width: W, height: H, pointerEvents: 'none', overflow: 'visible' }}>
        {/* Release Event → Zone left border (horizontal at Y_REL) */}
        <line x1={0} y1={Y_REL} x2={ZONE_LEFT} y2={Y_REL} stroke={green} strokeWidth={stroke} />
        <Arrowhead x={ZONE_LEFT} y={Y_REL} dir="right" color={green} />

        {/* Retain Event → Zone left border (horizontal at Y_RET) */}
        <line x1={0} y1={Y_RET} x2={ZONE_LEFT} y2={Y_RET} stroke={red} strokeWidth={stroke} />
        <Arrowhead x={ZONE_LEFT} y={Y_RET} dir="right" color={red} />

        {/* Release-after-Inv → Zone right border (horizontal at Y_REL, going left) */}
        <line x1={AFT_LEFT} y1={Y_REL} x2={ZONE_RIGHT} y2={Y_REL} stroke={green} strokeWidth={stroke} />
        <Arrowhead x={ZONE_RIGHT} y={Y_REL} dir="left" color={green} />

        {/* Retained-after-Inv → Zone right border (horizontal at Y_RET, going left) */}
        <line x1={AFT_LEFT} y1={Y_RET} x2={ZONE_RIGHT} y2={Y_RET} stroke={red} strokeWidth={stroke} />
        <Arrowhead x={ZONE_RIGHT} y={Y_RET} dir="left" color={red} />

        {/* Investigate Event → Investigator Factory (horizontal at Y_INV) */}
        <line x1={0} y1={Y_INV} x2={INVFACT_LEFT} y2={Y_INV} stroke={orange} strokeWidth={stroke} />
        <Arrowhead x={INVFACT_LEFT} y={Y_INV} dir="right" color={orange} />

        {/* Investigator → Queue */}
        <line x1={INVFACT_LEFT + INVFACT_W} y1={Y_INV} x2={QUEUE_LEFT} y2={Y_INV} stroke={purple} strokeWidth={stroke} />
        <Arrowhead x={QUEUE_LEFT} y={Y_INV} dir="right" color={purple} />

        {/* Queue → Agent */}
        <line x1={QUEUE_LEFT + QUEUE_W} y1={Y_INV} x2={AGENT_LEFT} y2={Y_INV} stroke={purple} strokeWidth={stroke} />
        <Arrowhead x={AGENT_LEFT} y={Y_INV} dir="right" color={purple} />

        {/* Agent → Cleared for Release (correct/uncertain) */}
        <line x1={AGENT_RIGHT} y1={Y_INV} x2={CLRREL_LEFT} y2={Y_INV} stroke={green} strokeWidth={stroke} />
        <Arrowhead x={CLRREL_LEFT} y={Y_INV} dir="right" color={green} />
        <text x={(AGENT_RIGHT + CLRREL_LEFT) / 2} y={Y_INV - 6}
              fontSize={9} fill={green} textAnchor="middle" fontWeight={700}>correct</text>

        {/* Cleared → Post-Inv Release */}
        <line x1={CLRREL_LEFT + CLRREL_W} y1={Y_INV} x2={POSTINV_LEFT} y2={Y_INV} stroke={green} strokeWidth={stroke} />
        <Arrowhead x={POSTINV_LEFT} y={Y_INV} dir="right" color={green} />

        {/* Post-Inv Release → Release-after-Inv (loop-back: up, then left) */}
        <polyline
          points={`${POSTINV_CX},${INV_ROW_TOP} ${POSTINV_CX},${Y_REL} ${AFT_RIGHT},${Y_REL}`}
          stroke={green} strokeWidth={stroke} fill="none" />
        <Arrowhead x={AFT_RIGHT} y={Y_REL} dir="left" color={green} />

        {/* Agent → Retained-after-Inv (incorrect: up, then left).
            Vertical leg at RETAIN_UP_X is outside the broker x range, so it
            doesn't pass through the box interior. */}
        <polyline
          points={`${RETAIN_UP_X},${INV_ROW_TOP} ${RETAIN_UP_X},${Y_RET} ${AFT_RIGHT},${Y_RET}`}
          stroke={red} strokeWidth={stroke} fill="none" />
        <Arrowhead x={AFT_RIGHT} y={Y_RET} dir="left" color={red} />
        <text x={RETAIN_UP_X + 4} y={INV_ROW_TOP - 4}
              fontSize={9} fill={red} textAnchor="start" fontWeight={700}>incorrect</text>
      </svg>

      {/* ── DB Store · Hub dashed zone (mirrors Order Validation / RT Risk / Transport on the left) ── */}
      <div style={{
        position: 'absolute', top: ZONE_TOP, left: ZONE_LEFT,
        width: ZONE_W, height: ZONE_H,
        border: '1px dashed var(--border-light)', borderRadius: 6,
        padding: '8px 10px', boxSizing: 'border-box',
      }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
          textAlign: 'center', marginBottom: 6,
          position: 'sticky', top: 0, zIndex: 2, background: '#fff', padding: '2px 4px',
        }}>
          Data Store
        </div>
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          gap: 6, height: 'calc(100% - 32px)', justifyContent: 'center',
        }}>
          <FactoryNode icon="💾" label="DB Store Factory" description="Insert + flag suspicious" sm
            tooltip="DB Store Factory — subscribes to Automated Release, Automated Retain, Release Post Inv. and Retain Post Inv. Inserts into european_custom.db and pushes to the live queue / SSE stream." />
          <Arrow down />
          <DBSinkNode count={stored} newCount={newStored}
            tooltip={`Custom Data Hub — ${fmt(stored)} total records (includes historical seed). ${fmt(newStored)} new records stored since the last simulation reset.`} />
        </div>
      </div>

      {/* Release Post Investigation broker — mirrors Automated Release */}
      <div style={{ position: 'absolute', top: RAFT_TOP, left: AFT_LEFT, width: AFT_W }}>
        <BrokerNode label="Release Post Inv." topicKey="RELEASE_POST_INV"
          count={ev.release_after_investigation_event} accent={green} sm width={AFT_W}
          tooltip="Release Post Inv. — terminal event for agent-cleared transactions. Stored to the DB without the suspicious flag." />
      </div>

      {/* Retain Post Investigation broker — mirrors Automated Retain */}
      <div style={{ position: 'absolute', top: RETAFT_TOP, left: AFT_LEFT, width: AFT_W }}>
        <BrokerNode label="Retain Post Inv." topicKey="RETAIN_POST_INV"
          count={ev.agent_retain_event} accent={red} sm width={AFT_W}
          tooltip="Retain Post Inv. — transactions the agent classified as non-compliant. Stored to the DB with the suspicious flag set." />
      </div>

      {/* ── Investigation Pipeline zone (dashed overlay around Investigator · Queue · Agent) ──
          Rendered BEFORE the three elements below so they draw on top of the border.
          Interior is transparent so SVG loop-back arrows remain visible through the zone.
          Label uses width: fit-content so its white background doesn't hide arrows that pass through. */}
      <div style={{
        position: 'absolute',
        left: INVFACT_LEFT - 14,
        top: INV_ROW_TOP - 41,
        width: (AGENT_RIGHT - INVFACT_LEFT) + 28,
        height: H - (INV_ROW_TOP - 41) - 2,
        border: '1px dashed var(--border-light)', borderRadius: 6,
        padding: '8px 10px', boxSizing: 'border-box',
        pointerEvents: 'none',
      }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
          textAlign: 'center',
          background: '#fff', padding: '2px 8px',
          width: 'fit-content', margin: '0 auto',
        }}>
          Investigation Pipeline
        </div>
      </div>

      {/* Investigator Factory */}
      <div style={{ position: 'absolute', top: INV_ROW_TOP, left: INVFACT_LEFT, width: INVFACT_W }}>
        <FactoryNode icon="🕵️" label="Investigator Factory" description="IE filter · FIFO queue" sm width={INVFACT_W}
          tooltip="Investigator Factory — filters Investigation Notifications for Ireland and enqueues them on the Investigation FIFO queue." />
      </div>

      {/* Investigation Queue — default gray palette (no accent override), matching
          the factory family visually. sm variant keeps it the same height as the
          surrounding factories so its center lands on Y_INV. */}
      <div style={{ position: 'absolute', top: INV_ROW_TOP - 2, left: QUEUE_LEFT, width: QUEUE_W }}>
        <QueueNode label="Investigation Queue" count={inv} sm
          tooltip="Investigation Queue — delayed backlog of cases awaiting the VAT Agent. Depth > 0 indicates a backlog." />
      </div>

      {/* VAT Agent Worker */}
      <div style={{ position: 'absolute', top: INV_ROW_TOP, left: AGENT_LEFT, width: AGENT_W }}>
        <FactoryNode icon="🤖" label="VAT Agent Worker" description="LM Studio · fraud detection" sm width={AGENT_W}
          tooltip="VAT Agent Worker — runs the local LLM (LM Studio) to produce a compliance verdict: incorrect / correct / uncertain." />
      </div>

      {/* Investigation Clearance broker */}
      <div style={{ position: 'absolute', top: INV_ROW_TOP, left: CLRREL_LEFT, width: CLRREL_W }}>
        <BrokerNode label="Investigation Clearance" topicKey="INVESTIGATION_CLEARANCE"
          count={ev.agent_release_event} accent={green} sm width={CLRREL_W}
          tooltip="Investigation Clearance — transactions the agent found compliant. Forwarded to the Post-Investigation Release factory." />
      </div>

      {/* Post-Investigation Release Factory */}
      <div style={{ position: 'absolute', top: INV_ROW_TOP, left: POSTINV_LEFT, width: POSTINV_W }}>
        <FactoryNode icon="🔓" label="Post-Inv. Release" description="agent-release + OV + arrival" sm width={POSTINV_W}
          tooltip="Post-Investigation Release Factory — waits for OV + Arrival on cleared transactions, then emits a Release After Investigation event." />
      </div>
    </div>
  )
}

// ── KPI strip ─────────────────────────────────────────────────────────────────

function KpiStrip({ pipeline }) {
  const ev = pipeline?.events || {}

  // Ingested: entry to the pipeline
  const ingested = ev.sales_order_event || 0

  // Released: Automated Release + Release Post Inv. (both release paths)
  const released = (ev.release_event                     || 0)
                 + (ev.release_after_investigation_event || 0)

  // Retained: Automated Retain + Retain Post Inv. (both retain paths)
  const retained = (ev.retain_event      || 0)
                 + (ev.agent_retain_event || 0)

  // Investigated: investigations the agent has completed (produced a verdict for)
  const investigated = (ev.agent_retain_event  || 0)
                     + (ev.agent_release_event || 0)

  // Under investigation: cumulative amber-routed minus completed = currently in-flight
  // (in the FIFO queue or being processed by the VAT Agent Worker)
  const underInvestigation = Math.max(
    0,
    (ev.investigate_event || 0) - investigated
  )

  const tiles = [
    { key: 'ingested',     label: 'Ingested',           value: ingested,          color: 'var(--eu-blue)',
      tooltip: 'Sales-order events fired by the simulation engine (entry to the pipeline).' },
    { key: 'released',     label: 'Released',           value: released,          color: '#1f7a3c',
      tooltip: 'Automated Release + Release Post Inv. — total transactions cleared for release (both automated and post-investigation).' },
    { key: 'retained',     label: 'Retained',           value: retained,          color: '#c0392b',
      tooltip: 'Automated Retain + Retain Post Inv. — total transactions flagged as suspicious and retained (both automated and post-investigation).' },
    { key: 'investigated', label: 'Investigated',       value: investigated,      color: '#e6820a',
      tooltip: 'Investigations the VAT Agent has completed (produced a verdict: correct, uncertain, or incorrect).' },
    { key: 'underInv',     label: 'Under Investigation', value: underInvestigation, color: '#9c27b0',
      tooltip: 'Transactions currently in the investigation pipeline — waiting in the FIFO queue or being analysed by the VAT Agent Worker.' },
  ]

  return (
    <div className="card section-gap">
      <div className="card-header">Pipeline KPIs</div>
      <div style={{ padding: '14px 20px', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {tiles.map((t) => (
          <div key={t.key} title={t.tooltip} style={{
            flex: '1 1 140px', minWidth: 140,
            background: t.color + '10', border: `1.5px solid ${t.color}55`,
            borderRadius: 'var(--radius)', padding: '10px 14px',
            cursor: 'help',
          }}>
            <div style={{
              fontSize: 10, color: t.color, fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
            }}>{t.label}</div>
            <div style={{
              fontSize: 24, fontWeight: 700, color: t.color, lineHeight: 1,
            }}>{fmt(t.value)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Pipeline Diagram ──────────────────────────────────────────────────────────

function PipelineDiagram({ pipeline }) {
  const ev     = pipeline?.events             || {}
  const q      = pipeline?.queues             || {}
  const rf     = pipeline?.risk_flags         || {}
  const inv    = pipeline?.investigation_queue ?? null
  const stored = pipeline?.stored_count        ?? null

  // Row 1: three parallel processing zones
  const OV_H = 94, RT_H = 230, AN_H = 94, LGAP = 10
  const ROW1_H = OV_H + LGAP + RT_H + LGAP + AN_H
  const yOV = OV_H / 2
  const yRT = OV_H + LGAP + RT_H / 2
  const yAN = OV_H + LGAP + RT_H + LGAP + AN_H / 2

  // Shared width for the three top zones so OV and Transport match the RT zone
  const ZONE_W = 440
  // Shared width for OV and Transport factories (so they match each other)
  const SIDE_FACTORY_W = 220
  // Shared width for the three row-1 output brokers (OV / RT Score / Arrival Notification)
  const OUT_BROKER_W = 170

  // RT zone internal row geometry (two stacked broker rows + fan-in to consolidation)
  const RT_ROW_H   = 84
  const RT_ROW_GAP = 10
  const RT_STACK_H = RT_ROW_H * 2 + RT_ROW_GAP    // 178
  const rtTopY     = RT_ROW_H / 2                  // 42  — center of row 1
  const rtBotY     = RT_ROW_H + RT_ROW_GAP + RT_ROW_H / 2  // 136 — center of row 2
  const rtOutY     = RT_STACK_H / 2                // 89  — fan-in output

  // Terminal-event sum = number of transactions stored to the DB since reset
  const newStored =
    (ev.release_event                     || 0) +
    (ev.retain_event                      || 0) +
    (ev.agent_retain_event                || 0) +
    (ev.release_after_investigation_event || 0)

  // Row 2: three event broker rows
  const EROW = 86, EGAP = 14
  const ROW2_H = EROW * 3 + EGAP * 2                 // 286
  const ryG = EROW / 2                               // 43
  const ryR = EROW + EGAP + EROW / 2                 // 143
  const ryA = EROW * 2 + EGAP * 2 + EROW / 2        // 243

  return (
    <div className="card section-gap">
      <div className="card-header">
        Pipeline Flow
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>live stream · ~5 Hz</span>
      </div>

      <div className="pipeline-scroll" style={{
        overflowX: 'auto', overflowY: 'hidden',
        padding: '20px 20px 20px',
        borderBottom: '1px solid var(--border-light)',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 'max-content' }}>

          {/* ══ MAIN FLOW — single horizontal row: Entry → zones → brokers → Release Factory → event brokers → DB Store ══ */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>

            {/* Entry Broker */}
            <Zone label="Entry">
              <BrokerNode label="Sales-order Event" topicKey="SALES_ORDER_EVENT"
                count={ev.sales_order_event} queueSize={q.sales_order_event} sm />
            </Zone>

            {/* FanOut: solid → OV + RT  |  dashed orange → Transport */}
            <FanOutMixedSVG height={ROW1_H} width={48} targets={[
              { y: yOV, color: '#adb5bd', dashed: false },
              { y: yRT, color: '#adb5bd', dashed: false },
              { y: yAN, color: '#e67e22', dashed: true  },
            ]} />

            {/* Three parallel zones stacked — all at ZONE_W so Row 1 is visually aligned */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>

              <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
                <Zone label="Order Validation" style={{ width: ZONE_W, boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
                    <FactoryNode icon="✅" label="Order Validation"
                      description="3–5 s · unlimited concurrency" sm width={SIDE_FACTORY_W}
                      tooltip="Order Validation Factory — async per-order task with uniform 3–5 s delay. Emits ORDER_VALIDATION events." />
                  </div>
                </Zone>
              </div>

              <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
                <Zone label="RT Risk Monitoring" style={{ width: ZONE_W, height: '100%', boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 0, height: '100%', justifyContent: 'flex-end' }}>
                    {/* Entry fan-out — mirrors the fan-in on the right */}
                    <FanOutSVG height={RT_STACK_H} targetYs={[rtTopY, rtBotY]} width={24} />
                    {/* Stacked RT1 + RT2 rows */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: RT_ROW_GAP }}>
                      <div style={{ height: RT_ROW_H, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <FactoryNode icon="⚖️" label="RT Risk Mon. 1" description="VAT ratio deviation" sm
                          tooltip="RT Risk Monitor 1 — flags transactions whose VAT-to-value ratio deviates from the supplier's historical baseline." />
                        <Arrow />
                        <BrokerNode label="RT Risk 1 Outcome" topicKey="RT_RISK_1_OUTCOME"
                          count={ev.rt_risk_1_outcome} sm
                          tooltip="RT_RISK_1_OUTCOME — one event per transaction with the VAT-ratio flag result.">
                          <FlaggedBadge flagged={rf.rt_risk_1_flagged} total={ev.rt_risk_1_outcome} />
                        </BrokerNode>
                      </div>
                      <div style={{ height: RT_ROW_H, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <FactoryNode icon="🔍" label="RT Risk Mon. 2" description="Watchlist lookup" sm
                          tooltip="RT Risk Monitor 2 — flags transactions whose seller or route appears on the active watchlist." />
                        <Arrow />
                        <BrokerNode label="RT Risk 2 Outcome" topicKey="RT_RISK_2_OUTCOME"
                          count={ev.rt_risk_2_outcome} sm
                          tooltip="RT_RISK_2_OUTCOME — one event per transaction with the watchlist lookup result.">
                          <FlaggedBadge flagged={rf.rt_risk_2_flagged} total={ev.rt_risk_2_outcome} />
                        </BrokerNode>
                      </div>
                    </div>
                    {/* FanIn: 2 rows → RT Consolidation */}
                    <FanInSVG height={RT_STACK_H} inputYs={[rtTopY, rtBotY]} outputY={rtOutY} width={36} />
                    {/* RT Consolidation — horizontally to the right of the two monitoring rows */}
                    <FactoryNode icon="🔄" label="RT Consolidation" description="GREEN / AMBER / RED" sm
                      tooltip="RT Consolidation — combines RT1 + RT2 into a single risk score: GREEN (none flagged), AMBER (one), RED (both)." />
                  </div>
                </Zone>
              </div>

              <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
                <Zone label="Transport" style={{ width: ZONE_W, boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
                    <FactoryNode icon="🚢" label="Transport"
                      description="exp. delay ~60 s · unlimited concurrency" sm width={SIDE_FACTORY_W}
                      tooltip="Transport / Arrival Notification — async per-order task with exponential-delay arrival (~60 s mean). Emits ARRIVAL_NOTIFICATION events." />
                  </div>
                </Zone>
              </div>

            </div>

            {/* Arrows: zones → brokers */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>
              <div style={{ height: OV_H,  display: 'flex', alignItems: 'center' }}><Arrow /></div>
              <div style={{ height: RT_H,  display: 'flex', alignItems: 'center' }}><Arrow /></div>
              <div style={{ height: AN_H,  display: 'flex', alignItems: 'center' }}><Arrow /></div>
            </div>

            {/* Three output brokers — same width, same default blue */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>
              <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Order Validation" topicKey="ORDER_VALIDATION"
                  count={ev.order_validation} sm width={OUT_BROKER_W}
                  tooltip="ORDER_VALIDATION — field-completeness outcome per order. Consumed by the Release Factory." />
              </div>
              <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="RT Score" topicKey="RT_SCORE"
                  count={ev.rt_score} sm width={OUT_BROKER_W}
                  tooltip="RT_SCORE — consolidated GREEN / AMBER / RED risk score per transaction. Consumed by the Release Factory.">
                  <ScoreBadges green={rf.rt_score_green} amber={rf.rt_score_amber} red={rf.rt_score_red} />
                </BrokerNode>
              </div>
              <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Arrival Notification" topicKey="ARRIVAL_NOTIFICATION"
                  count={ev.arrival_notification} sm width={OUT_BROKER_W}
                  tooltip="ARRIVAL_NOTIFICATION — emitted once goods arrive at destination. Required by the Release Factory." />
              </div>
            </div>

            {/* Fan-in: 3 output brokers → Release Factory */}
            <FanInSVG height={ROW1_H} inputYs={[yOV, yRT, yAN]} outputY={ROW1_H / 2} width={60} />

            {/* Release Factory — vertically centered at ROW1_H/2 to line up with the fan-in output */}
            <div style={{ height: ROW1_H, display: 'flex', alignItems: 'center' }}>
              <FactoryNode icon="🎯" label="Release Factory" description="routes by score + validation" sm
                tooltip="Release Factory — waits for RT Score + Order Validation + Arrival Notification on each transaction, then routes: GREEN→Release, RED→Retain, AMBER→Investigate." />
            </div>

            {/* Fan-out: Release Factory → 3 event brokers.
                Target Ys match row-1 output brokers (yOV, yRT, yAN) so vertical spacing is consistent. */}
            <FanOutSVG height={ROW1_H} targetYs={[yOV, yRT, yAN]} width={48} />

            {/* Three event brokers — heights match row-1 zones so centers land at yOV / yRT / yAN */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>
              <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Automated Release" topicKey="AUTOMATED_RELEASE"
                  count={ev.release_event} accent="#1f7a3c" sm width={OUT_BROKER_W}
                  tooltip="Automated Release — GREEN-path transactions cleared for storage without further investigation." />
              </div>
              <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Automated Retain" topicKey="AUTOMATED_RETAIN"
                  count={ev.retain_event} accent="#c0392b" sm width={OUT_BROKER_W}
                  tooltip="Automated Retain — RED-path transactions stored with the suspicious flag set." />
              </div>
              <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Investigation Notification" topicKey="INVESTIGATION_NOTIFICATION"
                  count={ev.investigate_event} accent="#e6820a" sm width={OUT_BROKER_W}
                  tooltip="Investigation Notification — AMBER-path transactions handed off to the investigation sub-pipeline." />
              </div>
            </div>

            {/* Middle section: DB Store Factory + Hub (grouped in a dashed zone) + After-Inv brokers
                (mirroring event brokers) + inline investigation pipeline along the bottom.
                Absolute-positioned canvas sized to ROW1_H; Y coordinates locked to yOV/yRT/yAN from the parent. */}
            <MiddleSection ev={ev} rf={rf} inv={inv} stored={stored} newStored={newStored}
              H={ROW1_H} yRel={yOV} yRet={yRT} yInv={yAN} />

          </div>

        </div>
      </div>

      {/* Legend */}
      <div style={{ padding: '10px 20px 16px', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', borderTop: '1px solid var(--border-light)' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)' }}>Legend:</span>

        {/* Element types */}
        <LegendItem color="var(--eu-blue)" bg="var(--eu-blue-light)" label="Broker" />
        <LegendItem color="#868e96" bg="#f8f9fa" label="Factory" />
        <LegendItem color="#868e96" bg="#eceff1" label="Queue (FIFO)" dashed />
        <LegendItem color="#0284c7" bg="#e0f2fe" label="Custom Data Hub (MongoDB)" />
        <LegendItem color="var(--text-muted)" bg="#ffffff" label="Processing zone" dashed />

        {/* Sub-box / arrow color coding */}
        <LegendItem color="#1f7a3c" bg="#e8f5e9" label="Release (automated + post inv.)" />
        <LegendItem color="#c0392b" bg="#fde8e8" label="Retain (automated + post inv.)" />
        <LegendItem color="#e6820a" bg="#fff3e0" label="Investigation notification" />
        <LegendItem color="#9c27b0" bg="#fdf6ff" label="Investigation flow" />
        <LegendItem color="#e67e22" bg="#fff8f0" label="Transport / Arrival" dashed />

        <div style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
          Brokers all share the blue outer border — the inner sub-box carries the differentiating color.
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
  { key: 'release_event',                       label: 'Automated Release',                factory: 'Release Factory (GREEN)',             color: '#1f7a3c' },
  { key: 'retain_event',                        label: 'Automated Retain',                 factory: 'Retain Factory (RED)',                color: '#c0392b' },
  { key: 'investigate_event',                   label: 'Investigation Notification',       factory: 'Investigate Dispatch Factory (AMBER)', color: '#e6820a' },
  { key: 'agent_retain_event',                  label: 'Retain Post Inv.',                 factory: 'Investigation Agent Worker',          color: '#c0392b' },
  { key: 'agent_release_event',                 label: 'Investigation Clearance',          factory: 'Investigation Agent Worker',          color: '#1f7a3c' },
  { key: 'release_after_investigation_event',   label: 'Release Post Inv.',                factory: 'Release After Investigation Factory', color: '#2e7d32' },
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

  // One-shot REST refreshes — used as a fallback when the stream is unavailable,
  // and wired into the SimControls onRefresh so control actions feel instant.
  const refreshStatus   = useCallback(async () => { try { setStatus(await getSimStatus()) } catch {} }, [])
  const refreshPipeline = useCallback(async () => { try { setPipeline(await getPipelineStats()) } catch {} }, [])

  // Open the SSE stream once on mount. The backend pushes a consolidated
  // { status, pipeline } snapshot at ~5 Hz, giving us smooth event-by-event UI
  // updates without polling. A slow 15 s REST safety-net poll covers the rare
  // case where the stream drops (e.g. backend restart).
  useEffect(() => {
    // Initial REST fetch so the page paints immediately rather than waiting for
    // the first SSE frame.
    refreshStatus()
    refreshPipeline()

    const es = openSimStateStream(
      (snap) => {
        if (snap?.status)   setStatus(snap.status)
        if (snap?.pipeline) setPipeline(snap.pipeline)
      },
      () => {
        // Connection error — EventSource will auto-reconnect. Do nothing here;
        // the safety-net interval below will keep the UI fresh meanwhile.
      }
    )

    const safetyId = setInterval(() => {
      // Only polls if the stream isn't delivering — acts as a last-resort
      // backstop. At 15 s it has negligible load impact.
      refreshStatus()
      refreshPipeline()
    }, 15000)

    return () => {
      es.close()
      clearInterval(safetyId)
    }
  }, [refreshStatus, refreshPipeline])

  return (
    <div className="page-container">
      <div className="page-title">Simulation</div>
      <div className="page-subtitle">
        Control the simulation and monitor the pub/sub pipeline in real time
      </div>

      <SimControls status={status} onRefresh={() => { refreshStatus(); refreshPipeline() }} />
      <KpiStrip pipeline={pipeline} />
      <PipelineDiagram pipeline={pipeline} status={status} />
      <EventCountsTable pipeline={pipeline} />
    </div>
  )
}
