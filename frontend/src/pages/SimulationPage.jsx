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

function FactoryNode({ label, description, icon, accent, sm, tooltip, width, count, countLabel }) {
  const defaultMinW = sm ? 86 : 120
  // accent is the inner-content + border color; falls back to the neutral
  // factory grey when not provided.
  const accentColor = accent || 'var(--border)'
  return (
    <div
      title={tooltip}
      style={{
        background: accent ? accent + '12' : '#f8f9fa',
        border: `1px solid ${accentColor}`,
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
      {count != null && (
        <div style={{ marginTop: 4 }}>
          <div style={{
            fontSize: sm ? 16 : 18, fontWeight: 700,
            color: accent ? accent : 'var(--text-primary)',
            lineHeight: 1,
          }}>
            {fmt(count)}
          </div>
          {countLabel && (
            <div style={{ fontSize: 7, color: 'var(--text-muted)', marginTop: 1, lineHeight: 1 }}>
              {countLabel}
            </div>
          )}
        </div>
      )}
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
      <span style={{ background: '#fde8e8', color: '#c0392b', border: '1px solid #f5c6cb', padding: '1px 5px', borderRadius: 8, fontSize: 9, fontWeight: 700 }}>● {fmt(red)}</span>
      <span style={{ background: '#fff3cd', color: '#856404', border: '1px solid #ffc107', padding: '1px 5px', borderRadius: 8, fontSize: 9, fontWeight: 700 }}>● {fmt(amber)}</span>
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

// Fan-out with per-target dashed style (all arrows now share the neutral grey
// stroke). The vertical spine is split into per-pair segments so the carrier
// of any dashed branch is itself dashed — this means the vertical leg from
// the Sales-order Event broker down to Goods Transport (dashed branch) appears
// dashed end-to-end, matching the horizontal Goods Transport extension.
function FanOutMixedSVG({ height, targets, width = 56 }) {
  if (!targets?.length) return null
  const spineX = 8
  const grey   = '#adb5bd'
  // Sort targets top→bottom so we can iterate adjacent pairs to split the spine.
  const sorted = [...targets].sort((a, b) => a.y - b.y)
  return (
    <svg width={width} height={height} style={{ flex: `0 0 ${width}px`, overflow: 'visible' }}>
      {sorted.slice(0, -1).map((t, i) => {
        const next = sorted[i + 1]
        const dash = (t.dashed || next.dashed) ? '4,3' : undefined
        return (
          <line key={`spine-${i}`} x1={spineX} y1={t.y} x2={spineX} y2={next.y}
            stroke={grey} strokeWidth={2} strokeDasharray={dash} />
        )
      })}
      {targets.map((t, i) => {
        const dash = t.dashed ? '4,3' : undefined
        return (
          <g key={i}>
            <circle cx={spineX} cy={t.y} r={3} fill={grey} />
            <line x1={spineX} y1={t.y} x2={width - 6} y2={t.y}
              stroke={grey} strokeWidth={2} strokeDasharray={dash} />
            <polygon points={`${width-6},${t.y-4} ${width},${t.y} ${width-6},${t.y+4}`} fill={grey} />
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
// than the individual elements, like Sales Order Validation / Real-Time Risk
// Assessment / Goods Transport zones on the left.
//
// Loop-back arrows:
//   Post-Inv Release → Release-after-Inv  (green, bottom → top)
//   VAT Agent        → Retained-after-Inv (red, "incorrect" branch)
// Vertical legs are routed OUTSIDE the after-Inv broker x range so the lines
// don't pass through the box interiors.
function MiddleSection({ ev, rf, customs, tax, taxRunning, stored, newStored, H, yRel, yRet, yInv }) {
  const Y_REL = yRel
  const Y_RET = yRet
  const Y_INV = yInv

  // Incoming-arrow runway on the left edge
  const IN_ARROW_W = 60

  // ── DB Store · Hub group (dashed zone) ───────────────────────────────────
  // The zone extends from y=10 down to y=300 — wide enough to encompass both
  // Y_REL (Release Post Inv at yOV ≈ 47) and Y_RET (Retain Post Inv at yRT
  // ≈ 219) so the After-Inv broker terminal arrows land cleanly on its right
  // border. The bottom edge sits 12 px above the Customs row top (312).
  const ZONE_LEFT   = IN_ARROW_W
  const ZONE_W      = 210
  const ZONE_TOP    = 10
  const ZONE_H      = 290
  const ZONE_RIGHT  = ZONE_LEFT + ZONE_W       // 270
  const ZONE_BOTTOM = ZONE_TOP + ZONE_H        // 300

  // ── After-Inv brokers (mirror Release / Retain event brokers) ────────────
  const AFT_W = 150
  const AFT_H = 78
  const AFT_LEFT   = ZONE_RIGHT + 56          // 326
  const AFT_RIGHT  = AFT_LEFT + AFT_W         // 476
  const RAFT_TOP   = Y_REL - AFT_H / 2
  const RETAFT_TOP = Y_RET - AFT_H / 2

  // ── Two-entity bottom band: Customs Office above, Tax Office below ───────
  //
  // Each office is a horizontal chain Listener → Queue → Officer wrapped in
  // its own dashed zone. The Tax Office additionally has the VAT Agent
  // stacked below the Tax Officer (Tax-only tool, manually triggered).
  // Inter-office L-shape arrows connect Customs Officer → Tax Queue
  // (escalate) and Tax Officer → Customs Queue (recommendation back).
  //
  // Y positions are chosen so the two rows DO NOT overlap with the upper
  // band's After-Inv brokers (which sit at Y_REL and Y_RET).
  // The Customs Office dashed zone wraps the row blocks with a 24 px label
  // padding above CUSTOMS_ROW_TOP, so the zone top sits at Y_CUSTOMS - 52.
  // Y_CUSTOMS = 360 puts the Customs zone top at y=308, leaving an 8 px gap
  // below the Data Store zone bottom (ZONE_BOTTOM = 300). The Tax row sits
  // 170 px below to preserve the original inter-row gap and inter-zone
  // arrow geometry.
  // Tax row aligns with the Investigation Notification broker (yInv)
  // so the "investigate → tax" arrow runs straight across horizontally.
  // Minimum Y_TAX ensures it stays below the Customs row.
  const Y_TAX     = Math.max(Y_INV, ZONE_BOTTOM + 170)
  // Customs row sits between the Data Store zone and the Tax row,
  // with 12 px clearance below the zone and enough room for its blocks.
  const Y_CUSTOMS = ZONE_BOTTOM + 12 + 28       // zone bottom + gap + half block height

  // Block widths for the bottom band — uniform across both rows so the
  // listeners, queues and officers are vertically aligned.
  const LSTN_W   = 140
  const QUEUE_W  = 150
  const OFCR_W   = 180

  const LSTN_LEFT  = IN_ARROW_W
  const QUEUE_LEFT = LSTN_LEFT  + LSTN_W  + 22
  const OFCR_LEFT  = QUEUE_LEFT + QUEUE_W + 22
  const OFCR_RIGHT = OFCR_LEFT  + OFCR_W

  // Block heights — uniform sm-style factory/queue boxes.
  const ROW_BLOCK_H = 56
  const CUSTOMS_ROW_TOP = Y_CUSTOMS - ROW_BLOCK_H / 2
  const CUSTOMS_ROW_BOT = Y_CUSTOMS + ROW_BLOCK_H / 2
  const TAX_ROW_TOP     = Y_TAX     - ROW_BLOCK_H / 2
  const TAX_ROW_BOT     = Y_TAX     + ROW_BLOCK_H / 2

  // VAT Fraud Detection Agent stacked below the Tax Officer.
  const AGENT_W       = OFCR_W
  const AGENT_LEFT    = OFCR_LEFT
  const AGENT_BLOCK_H = 86                              // taller to fit the "under analysis" count line
  const AGENT_GAP_Y   = 30                              // gap between Tax Officer bottom and Agent top
  const AGENT_TOP     = TAX_ROW_BOT + AGENT_GAP_Y
  const AGENT_BOTTOM  = AGENT_TOP + AGENT_BLOCK_H
  const AGENT_CX      = AGENT_LEFT + AGENT_W / 2

  // Investigation Clearance broker + Post-Inv Release factory live OUTSIDE
  // the Customs Office zone, to the right of the Customs Officer block, at
  // the same y so the Customs Officer's "release" decision can flow into
  // them on a clean horizontal line.
  const CLRREL_W     = 126
  const CLRREL_LEFT  = OFCR_RIGHT + 28
  const POSTINV_W    = 158
  const POSTINV_LEFT = CLRREL_LEFT + CLRREL_W + 24
  const POSTINV_RIGHT = POSTINV_LEFT + POSTINV_W

  // Total canvas width — leaves room on the right for the Post-Inv loop-back column
  const W = POSTINV_RIGHT + 48

  // Centering helpers
  const QUEUE_CX  = QUEUE_LEFT  + QUEUE_W  / 2
  const OFCR_CX   = OFCR_LEFT   + OFCR_W   / 2

  // ── Arrival → Post-Inv Release supplementary arrow ───────────────────────
  // The Post-Inv Release factory correlates Investigation Clearance + Order
  // Validation + Arrival Notification. The OV/Clearance branches arrive via
  // the Customs Officer release path; this draws the missing Arrival branch
  // as a U-shape that exits the upper-band Arrival broker area, descends
  // BELOW everything (Tax Office zone + VAT Agent + inter-zone arrows),
  // runs horizontally under them, and rises back up into the Post-Inv
  // Release block from below. Routing the arrow under the schema avoids
  // crossing the Customs/Tax zones and the escalate / recommend arrows.
  //
  // ARRIVAL_START_X is the negative offset (in MiddleSection-local
  // coordinates) of the FanIn spine corner where the existing Arrival arrow
  // turns upward to feed Release Factory. Derived statically from the fixed
  // upper-band widths between MiddleSection's left edge and the FanIn:
  //   AUTOMATED brokers column (OUT_BROKER_W = 170)
  // + FanOut SVG (48)
  // + Release Factory wrapper (≈ 135 — sm factory + padding)
  // + FanIn SVG (60), spine at width-8 = 52 from its right edge
  // Start point ≈ -(170 + 48 + 135 + 60 - 52) ≈ -361.
  const ARRIVAL_START_X = -361
  const ARRIVAL_BELOW_Y = AGENT_BOTTOM + 24    // 16 px below the VAT Agent

  // Effective canvas height — extends below H to accommodate the Tax row,
  // the VAT Agent stacked below it, AND the arrival U-shape's horizontal
  // leg that runs under everything.
  const Heff = Math.max(H, ARRIVAL_BELOW_Y + 16)

  // ── Loop-back routing ────────────────────────────────────────────────────
  // Vertical legs MUST lie outside the after-Inv broker x range
  // [AFT_LEFT, AFT_RIGHT] so they don't cross the broker interiors.
  //
  // Post-Inv Release → Release-after-Inv: vertical at POSTINV_CX (>> AFT_RIGHT)
  const POSTINV_CX = POSTINV_LEFT + POSTINV_W / 2
  // Customs Officer "retain" → Retained-after-Inv. The vertical leg sits on
  // the right portion of the Customs Officer top edge so it lands on the
  // officer (where the human decision is taken) AND clears the after-Inv
  // broker x range. AFT_RIGHT + 24 = 500 falls inside OFCR_LEFT..OFCR_RIGHT.
  const RETAIN_UP_X = AFT_RIGHT + 24          // 500 — inside OFCR x range

  // ── Inter-zone L-shape arrows (escalate / recommend) ─────────────────────
  // Each arrow runs Officer → midpoint horizontal → vertical → other Queue.
  // Vertical legs are offset on opposite sides of the Queue/Officer centres
  // so the two arrows don't share the same x and visually merge.
  const MID_Y          = (CUSTOMS_ROW_BOT + TAX_ROW_TOP) / 2   // 425
  const ESC_MID_Y      = MID_Y - 10                             // 415
  const REC_MID_Y      = MID_Y + 10                             // 435
  const ESC_OFCR_X     = OFCR_CX - 24                           // 460
  const REC_OFCR_X     = OFCR_CX + 24                           // 508
  const ESC_QUEUE_X    = QUEUE_CX - 30                          // 267
  const REC_QUEUE_X    = QUEUE_CX + 30                          // 327

  const stroke = 2
  // All connector lines + arrowheads use this single neutral grey. Semantic
  // colour is reserved for the text labels next to each arrow (release / retain
  // / escalate / recommend / trigger / verdict) so the eye still parses
  // meaning at a glance.
  const grey   = '#adb5bd'
  // Label colours (text only — line strokes stay grey)
  const green  = '#1f7a3c'
  const red    = '#c0392b'
  const indigo = '#6366f1'
  const orange = '#e6820a'

  // Small helper for arrowheads at a point, given direction
  const Arrowhead = ({ x, y, dir, color = grey }) => {
    const s = 6
    let pts
    if      (dir === 'right') pts = `${x-s},${y-s} ${x},${y} ${x-s},${y+s}`
    else if (dir === 'left')  pts = `${x+s},${y-s} ${x},${y} ${x+s},${y+s}`
    else if (dir === 'down')  pts = `${x-s},${y-s} ${x},${y} ${x+s},${y-s}`
    else                      pts = `${x-s},${y+s} ${x},${y} ${x+s},${y+s}`
    return <polygon points={pts} fill={color} />
  }

  // Bidirectional consult arrow between Tax Officer and the VAT Agent below.
  // Two parallel vertical legs offset from the central axis: left leg =
  // trigger (down), right leg = verdict (up).
  const CONSULT_DX  = 14
  const CONSULT_TOP = TAX_ROW_BOT + 1                // 1 px below Tax Officer bottom
  const CONSULT_BOT = AGENT_TOP - 1                  // 1 px above agent top edge

  return (
    <div style={{ position: 'relative', width: W, height: Heff, flexShrink: 0 }}>
      {/* Arrow/connector overlay */}
      <svg style={{ position: 'absolute', top: 0, left: 0, width: W, height: Heff, pointerEvents: 'none', overflow: 'visible' }}>
        {/* Release Event → DB Store zone left border (horizontal at Y_REL).
            GREEN automated releases still flow directly into terminal storage. */}
        <line x1={0} y1={Y_REL} x2={ZONE_LEFT} y2={Y_REL} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={ZONE_LEFT} y={Y_REL} dir="right" />

        {/* Retain Event → Customs Listener (corner: right then down then right).
            RED automated retains are NO LONGER stored directly — they enter the
            Customs queue for an officer decision. */}
        <polyline
          points={`0,${Y_RET} ${LSTN_LEFT - 30},${Y_RET} ${LSTN_LEFT - 30},${Y_CUSTOMS} ${LSTN_LEFT},${Y_CUSTOMS}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={LSTN_LEFT} y={Y_CUSTOMS} dir="right" />
        <text x={LSTN_LEFT - 24} y={(Y_RET + Y_CUSTOMS) / 2}
              fontSize={9} fill={red} textAnchor="start" fontWeight={700}
              transform={`rotate(-90, ${LSTN_LEFT - 24}, ${(Y_RET + Y_CUSTOMS) / 2})`}>retain → customs</text>

        {/* Sales Order for Investigation → Tax Listener (corner: right then
            down then right). AMBER routed transactions enter the Tax queue. */}
        <polyline
          points={`0,${Y_INV} ${LSTN_LEFT - 30},${Y_INV} ${LSTN_LEFT - 30},${Y_TAX} ${LSTN_LEFT},${Y_TAX}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={LSTN_LEFT} y={Y_TAX} dir="right" />
        <text x={LSTN_LEFT - 26} y={Y_INV - 6}
              fontSize={9} fill={orange} textAnchor="start" fontWeight={700}>investigate → tax</text>

        {/* Release-after-Inv → Zone right border (horizontal at Y_REL, going left) */}
        <line x1={AFT_LEFT} y1={Y_REL} x2={ZONE_RIGHT} y2={Y_REL} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={ZONE_RIGHT} y={Y_REL} dir="left" />

        {/* Retained-after-Inv → Zone right border (horizontal at Y_RET, going left) */}
        <line x1={AFT_LEFT} y1={Y_RET} x2={ZONE_RIGHT} y2={Y_RET} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={ZONE_RIGHT} y={Y_RET} dir="left" />

        {/* ── Customs row internal chain ── */}
        {/* Customs Listener → Customs Queue */}
        <line x1={LSTN_LEFT + LSTN_W} y1={Y_CUSTOMS} x2={QUEUE_LEFT} y2={Y_CUSTOMS} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={QUEUE_LEFT} y={Y_CUSTOMS} dir="right" />
        {/* Customs Queue → Customs Officer */}
        <line x1={QUEUE_LEFT + QUEUE_W} y1={Y_CUSTOMS} x2={OFCR_LEFT} y2={Y_CUSTOMS} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={OFCR_LEFT} y={Y_CUSTOMS} dir="right" />

        {/* ── Tax row internal chain ── */}
        {/* Tax Listener → Tax Queue */}
        <line x1={LSTN_LEFT + LSTN_W} y1={Y_TAX} x2={QUEUE_LEFT} y2={Y_TAX} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={QUEUE_LEFT} y={Y_TAX} dir="right" />
        {/* Tax Queue → Tax Officer */}
        <line x1={QUEUE_LEFT + QUEUE_W} y1={Y_TAX} x2={OFCR_LEFT} y2={Y_TAX} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={OFCR_LEFT} y={Y_TAX} dir="right" />

        {/* ── Inter-zone arrows ── */}
        {/* Customs Officer → Tax Queue (escalate). L-shape: down, left, down. */}
        <polyline
          points={`${ESC_OFCR_X},${CUSTOMS_ROW_BOT} ${ESC_OFCR_X},${ESC_MID_Y} ${ESC_QUEUE_X},${ESC_MID_Y} ${ESC_QUEUE_X},${TAX_ROW_TOP}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={ESC_QUEUE_X} y={TAX_ROW_TOP} dir="down" />
        <text x={(ESC_OFCR_X + ESC_QUEUE_X) / 2} y={ESC_MID_Y - 4}
              fontSize={9} fill={orange} textAnchor="middle" fontWeight={700}>escalate</text>

        {/* Tax Officer → Customs Queue (recommend). L-shape: up, left, up. */}
        <polyline
          points={`${REC_OFCR_X},${TAX_ROW_TOP} ${REC_OFCR_X},${REC_MID_Y} ${REC_QUEUE_X},${REC_MID_Y} ${REC_QUEUE_X},${CUSTOMS_ROW_BOT}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={REC_QUEUE_X} y={CUSTOMS_ROW_BOT} dir="up" />
        <text x={(REC_OFCR_X + REC_QUEUE_X) / 2} y={REC_MID_Y + 12}
              fontSize={9} fill={indigo} textAnchor="middle" fontWeight={700}>recommend</text>

        {/* ── Customs Officer terminal decisions ── */}
        {/* Customs Officer → Investigation Clearance (release at Y_CUSTOMS) */}
        <line x1={OFCR_RIGHT} y1={Y_CUSTOMS} x2={CLRREL_LEFT} y2={Y_CUSTOMS} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={CLRREL_LEFT} y={Y_CUSTOMS} dir="right" />
        <text x={(OFCR_RIGHT + CLRREL_LEFT) / 2} y={Y_CUSTOMS - 6}
              fontSize={9} fill={green} textAnchor="middle" fontWeight={700}>release</text>

        {/* Cleared → Post-Inv Release */}
        <line x1={CLRREL_LEFT + CLRREL_W} y1={Y_CUSTOMS} x2={POSTINV_LEFT} y2={Y_CUSTOMS} stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={POSTINV_LEFT} y={Y_CUSTOMS} dir="right" />

        {/* Post-Inv Release → Release-after-Inv (loop-back: up, then left) */}
        <polyline
          points={`${POSTINV_CX},${CUSTOMS_ROW_TOP} ${POSTINV_CX},${Y_REL} ${AFT_RIGHT},${Y_REL}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={AFT_RIGHT} y={Y_REL} dir="left" />

        {/* Customs Officer "retain" decision → Retained-after-Inv (loop-back:
            up, then left). Vertical leg originates on the Customs Officer's
            top edge — the human chooses to retain rather than release. */}
        <polyline
          points={`${RETAIN_UP_X},${CUSTOMS_ROW_TOP} ${RETAIN_UP_X},${Y_RET} ${AFT_RIGHT},${Y_RET}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={AFT_RIGHT} y={Y_RET} dir="left" />
        <text x={RETAIN_UP_X + 4} y={CUSTOMS_ROW_TOP - 4}
              fontSize={9} fill={red} textAnchor="start" fontWeight={700}>retain</text>

        {/* Tax Officer ⇄ VAT Fraud Detection Agent — bidirectional vertical
            consult arrow. Two parallel legs: left = trigger (down), right =
            verdict (up). */}
        <line x1={OFCR_CX - CONSULT_DX} y1={CONSULT_TOP} x2={OFCR_CX - CONSULT_DX} y2={CONSULT_BOT}
          stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={OFCR_CX - CONSULT_DX} y={CONSULT_BOT} dir="down" />
        <line x1={OFCR_CX + CONSULT_DX} y1={CONSULT_BOT} x2={OFCR_CX + CONSULT_DX} y2={CONSULT_TOP}
          stroke={grey} strokeWidth={stroke} />
        <Arrowhead x={OFCR_CX + CONSULT_DX} y={CONSULT_TOP} dir="up" />
        <text x={OFCR_CX - CONSULT_DX - 4} y={(CONSULT_TOP + CONSULT_BOT) / 2}
              fontSize={9} fill={indigo} textAnchor="end" fontWeight={700} dominantBaseline="middle">trigger</text>
        <text x={OFCR_CX + CONSULT_DX + 4} y={(CONSULT_TOP + CONSULT_BOT) / 2}
              fontSize={9} fill={indigo} textAnchor="start" fontWeight={700} dominantBaseline="middle">verdict</text>

        {/* Arrival Notification → Post-Inv Release supplementary input.
            U-shape: starts at the FanIn corner where the existing Arrival
            arrow turns up to Release Factory, descends BELOW the entire
            bottom band (Customs zone + Tax zone + VAT Agent + inter-zone
            arrows), runs right under them, then rises into the bottom edge
            of the Post-Inv Release block. Routing under the schema keeps
            the line clear of the escalate / recommend / consult arrows.
            Drawn at negative x — relies on the SVG's overflow:visible. */}
        <polyline
          points={`${ARRIVAL_START_X},${Y_INV} ${ARRIVAL_START_X},${ARRIVAL_BELOW_Y} ${POSTINV_CX},${ARRIVAL_BELOW_Y} ${POSTINV_CX},${CUSTOMS_ROW_BOT}`}
          stroke={grey} strokeWidth={stroke} fill="none" />
        <Arrowhead x={POSTINV_CX} y={CUSTOMS_ROW_BOT} dir="up" />
        <text x={ARRIVAL_START_X + 4} y={Y_INV - 6}
              fontSize={9} fill="var(--text-muted)" textAnchor="start" fontWeight={700}>arrival</text>
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
            tooltip="DB Store Factory — subscribes to Sales Order Release, Release Post Inv. and Retain Post Inv. Inserts into european_custom.db and pushes to the live queue / SSE stream." />
          <Arrow down />
          <DBSinkNode count={stored} newCount={newStored}
            tooltip={`Custom Data Hub — ${fmt(stored)} total records (includes historical seed). ${fmt(newStored)} new records stored since the last simulation reset.`} />
        </div>
      </div>

      {/* Release Post Investigation broker — mirrors Sales Order Release */}
      <div style={{ position: 'absolute', top: RAFT_TOP, left: AFT_LEFT, width: AFT_W }}>
        <BrokerNode label="Release Post Inv." topicKey="RELEASE_POST_INV"
          count={ev.release_after_investigation_event} accent={green} sm width={AFT_W}
          tooltip="Release Post Inv. — terminal event for officer-cleared transactions. Stored to the DB without the suspicious flag." />
      </div>

      {/* Retain Post Investigation broker — mirrors Sales Order Retained */}
      <div style={{ position: 'absolute', top: RETAFT_TOP, left: AFT_LEFT, width: AFT_W }}>
        <BrokerNode label="Retain Post Inv." topicKey="RETAIN_POST_INV"
          count={ev.agent_retain_event} accent={red} sm width={AFT_W}
          tooltip="Retain Post Inv. — transactions the Customs officer retained. Stored to the DB with the suspicious flag set." />
      </div>

      {/* ── Customs Office dashed zone ──
          Wraps the Customs Listener / Customs Queue / Customs Officer chain
          on the Customs row. Rendered BEFORE the inner blocks so they paint
          on top of the border. Interior is non-interactive so SVG arrows
          remain visible through the zone. The label uses width: fit-content
          so its white background doesn't hide arrows passing through. */}
      <div style={{
        position: 'absolute',
        left: LSTN_LEFT - 14,
        top: CUSTOMS_ROW_TOP - 24,
        width: (OFCR_RIGHT - LSTN_LEFT) + 28,
        height: ROW_BLOCK_H + 36,
        border: '1px dashed var(--border-light)', borderRadius: 6,
        padding: '4px 10px', boxSizing: 'border-box',
        pointerEvents: 'none',
      }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
          textAlign: 'center',
          background: '#fff', padding: '2px 8px',
          width: 'fit-content', margin: '0 auto',
        }}>
          Customs Office · Final Decision
        </div>
      </div>

      {/* ── Tax Office dashed zone ──
          Wraps the Tax Listener / Tax Queue / Tax Officer chain AND the VAT
          Fraud Detection Agent stacked underneath the Tax Officer. */}
      <div style={{
        position: 'absolute',
        left: LSTN_LEFT - 14,
        top: TAX_ROW_TOP - 24,
        width: (OFCR_RIGHT - LSTN_LEFT) + 28,
        height: (AGENT_BOTTOM + 14) - (TAX_ROW_TOP - 24),
        border: '1px dashed var(--border-light)', borderRadius: 6,
        padding: '4px 10px', boxSizing: 'border-box',
        pointerEvents: 'none',
      }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
          textAlign: 'center',
          background: '#fff', padding: '2px 8px',
          width: 'fit-content', margin: '0 auto',
        }}>
          Tax Office · Recommendation + Agent
        </div>
      </div>

      {/* ── Customs row blocks ── */}
      {/* Customs Listener — subscribes to RETAIN_EVENT and parks each
          transaction in the in-memory Customs queue for officer review. */}
      <div style={{ position: 'absolute', top: CUSTOMS_ROW_TOP, left: LSTN_LEFT, width: LSTN_W }}>
        <FactoryNode icon="📥" label="Customs Listener" description="parks RETAIN events" sm width={LSTN_W}
          tooltip="Customs Listener — subscribes to RETAIN_EVENT and pushes each RED-routed transaction into the in-memory Customs queue for the officer's final decision." />
      </div>

      {/* Customs Queue — depth from pipeline.customs_queue */}
      <div style={{ position: 'absolute', top: CUSTOMS_ROW_TOP - 2, left: QUEUE_LEFT, width: QUEUE_W }}>
        <QueueNode label="Customs Queue" count={customs} sm
          tooltip="Customs Queue — in-memory dict of transactions awaiting Customs officer action (release, retain, or escalate to Tax). Depth includes Tax-recommended items returned for the final Customs decision." />
      </div>

      {/* Customs Officer console — Revenue Guardian Customs page on :8080 */}
      <div style={{ position: 'absolute', top: CUSTOMS_ROW_TOP, left: OFCR_LEFT, width: OFCR_W }}>
        <FactoryNode icon="🛃" label="Customs Officer" description="@ revenue-guardian /customs" sm width={OFCR_W}
          accent={indigo}
          tooltip="Customs Officer Console — Revenue Guardian Customs page on http://localhost:8080. The officer reviews each Customs queue item and either releases, retains, or escalates the case to the Tax authority for advice. Customs is master — its decision is the terminal event." />
      </div>

      {/* ── Tax row blocks ── */}
      {/* Tax Listener — subscribes to INVESTIGATE_EVENT and parks each
          AMBER-routed transaction in the in-memory Tax queue. */}
      <div style={{ position: 'absolute', top: TAX_ROW_TOP, left: LSTN_LEFT, width: LSTN_W }}>
        <FactoryNode icon="📥" label="Tax Listener" description="parks INVESTIGATE events" sm width={LSTN_W}
          tooltip="Tax Listener — subscribes to INVESTIGATE_EVENT and pushes each AMBER-routed transaction into the in-memory Tax queue for analysis." />
      </div>

      {/* Tax Queue — depth from pipeline.tax_queue */}
      <div style={{ position: 'absolute', top: TAX_ROW_TOP - 2, left: QUEUE_LEFT, width: QUEUE_W }}>
        <QueueNode label="Tax Queue" count={tax} sm
          tooltip="Tax Queue — in-memory dict of transactions awaiting Tax officer analysis. Includes both AMBER-routed items and items escalated from the Customs queue." />
      </div>

      {/* Tax Officer console — Revenue Guardian Tax page on :8080 */}
      <div style={{ position: 'absolute', top: TAX_ROW_TOP, left: OFCR_LEFT, width: OFCR_W }}>
        <FactoryNode icon="🧑‍⚖️" label="Tax Officer" description="@ revenue-guardian /tax" sm width={OFCR_W}
          accent={indigo}
          tooltip="Tax Officer Console — Revenue Guardian Tax page on http://localhost:8080. The Tax officer triggers the VAT Fraud Detection Agent, then issues a release / retain RECOMMENDATION which is sent back to the Customs queue for the final decision." />
      </div>

      {/* VAT Fraud Detection Agent — sits BELOW the Tax Officer as a side
          consultation tool reached via the bidirectional consult arrow.
          Manually triggered by the Tax officer clicking "Run Agent". */}
      <div style={{ position: 'absolute', top: AGENT_TOP, left: AGENT_LEFT, width: AGENT_W }}>
        <FactoryNode icon="🤖" label="VAT Fraud Detection Agent" description="LM Studio · manually triggered" sm width={AGENT_W}
          count={taxRunning} countLabel="under analysis"
          tooltip="VAT Fraud Detection Agent — runs the local LLM (LM Studio) on demand when the Tax officer clicks Run Agent in the Revenue Guardian UI. The count shows how many Tax queue items are currently being analysed (agent_status = agent_running)." />
      </div>

      {/* Investigation Clearance broker — vertically centered on Y_CUSTOMS.
          BrokerNode renders ~14 px taller than the surrounding sm factories,
          so we offset its top edge upward to center it on the same baseline. */}
      <div style={{ position: 'absolute', top: CUSTOMS_ROW_TOP - 7, left: CLRREL_LEFT, width: CLRREL_W }}>
        <BrokerNode label="Investigation Clearance" topicKey="INVESTIGATION_CLEARANCE"
          count={ev.agent_release_event} accent={green} sm width={CLRREL_W}
          tooltip="Investigation Clearance — transactions the Customs officer cleared for release. Forwarded to the Post-Investigation Release factory." />
      </div>

      {/* Post-Investigation Release Factory */}
      <div style={{ position: 'absolute', top: CUSTOMS_ROW_TOP, left: POSTINV_LEFT, width: POSTINV_W }}>
        <FactoryNode icon="🔓" label="Post-Inv. Release" description="cleared + OV + arrival" sm width={POSTINV_W}
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

  // Released: Sales Order Release + Release Post Inv. (both release paths)
  const released = (ev.release_event                     || 0)
                 + (ev.release_after_investigation_event || 0)

  // Retained: Sales Order Retained + Retain Post Inv. (both retain paths)
  const retained = (ev.retain_event      || 0)
                 + (ev.agent_retain_event || 0)

  // Investigated: investigations the agent has completed (produced a verdict for)
  const investigated = (ev.agent_retain_event  || 0)
                     + (ev.agent_release_event || 0)

  // Under investigation: cumulative amber-routed minus completed = currently in-flight
  // (in the Tax queue or being processed by the VAT Fraud Detection Agent)
  const underInvestigation = Math.max(
    0,
    (ev.investigate_event || 0) - investigated
  )

  const tiles = [
    { key: 'ingested',     label: 'Ingested',           value: ingested,          color: 'var(--eu-blue)',
      tooltip: 'Sales-order events fired by the simulation engine (entry to the pipeline).' },
    { key: 'released',     label: 'Released',           value: released,          color: '#1f7a3c',
      tooltip: 'Sales Order Release + Release Post Inv. — total transactions cleared for release (both automated and post-investigation).' },
    { key: 'retained',     label: 'Retained',           value: retained,          color: '#c0392b',
      tooltip: 'Sales Order Retained + Retain Post Inv. — total transactions flagged as suspicious and retained (both automated and post-investigation).' },
    { key: 'investigated', label: 'Investigated',       value: investigated,      color: '#e6820a',
      tooltip: 'Investigations the VAT Fraud Detection Agent has completed (produced a verdict: correct, uncertain, or incorrect).' },
    { key: 'underInv',     label: 'Under Investigation', value: underInvestigation, color: '#9c27b0',
      tooltip: 'Transactions currently in the Tax queue — waiting for the Tax officer to act or being analysed by the VAT Fraud Detection Agent.' },
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
  const ev         = pipeline?.events             || {}
  const q          = pipeline?.queues             || {}
  const rf         = pipeline?.risk_flags         || {}
  // Two-entity model: separate Customs and Tax queues, each with its own
  // depth on the pipeline snapshot. taxRunning is the count of Tax-queue
  // items currently being analysed by the VAT Fraud Detection Agent.
  const customs    = pipeline?.customs_queue          ?? null
  const tax        = pipeline?.tax_queue              ?? null
  const taxRunning = pipeline?.tax_queue_agent_running ?? null
  const stored     = pipeline?.stored_count           ?? null

  // Row 1: three parallel processing zones
  // AN_H is taller so the Investigation Notification broker aligns
  // horizontally with the Tax Listener in the MiddleSection.
  const OV_H = 94, RT_H = 230, AN_H = 252, LGAP = 10
  const ROW1_H = OV_H + LGAP + RT_H + LGAP + AN_H
  const yOV = OV_H / 2
  const yRT = OV_H + LGAP + RT_H / 2
  const yAN = OV_H + LGAP + RT_H + LGAP + AN_H / 2

  // Shared width for the three top zones so Sales Order Validation and
  // Goods Transport match the Real-Time Risk Assessment zone
  const ZONE_W = 440
  // Shared width for the Sales Order Validation and Goods Transport factories
  // so they match each other. Each fills its parent zone's content area
  // (ZONE_W − 2× zone padding 10 = 420). With justifyContent: center the
  // factory is visually centered AND its right edge lines up with the
  // Risk Score Consolidation factory on the right side of the Real-Time
  // Risk Assessment zone (also bounded by the same zone padding).
  const SIDE_FACTORY_W = 420
  // Shared width for the three row-1 output brokers
  // (Sales Order Validation / RT Score / Goods Arrival Notification)
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

      {/* Top scrollbar: a zero-height mirror that syncs scroll position
          with the main pipeline container below. */}
      <div
        className="pipeline-scroll-top"
        style={{ overflowX: 'auto', overflowY: 'hidden' }}
        onScroll={(e) => {
          const bot = e.currentTarget.nextElementSibling;
          if (bot) bot.scrollLeft = e.currentTarget.scrollLeft;
        }}
      >
        {/* Invisible spacer matching the pipeline content width */}
        <div style={{ height: 1 }} className="pipeline-scroll-spacer" />
      </div>

      <div ref={pipelineRef} className="pipeline-scroll" style={{
        overflowX: 'auto', overflowY: 'hidden',
        padding: '20px 20px 20px',
        borderBottom: '1px solid var(--border-light)',
      }}
        onScroll={(e) => {
          const top = e.currentTarget.previousElementSibling;
          if (top) top.scrollLeft = e.currentTarget.scrollLeft;
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 'max-content' }}>

          {/* ══ MAIN FLOW — single horizontal row: Entry → zones → brokers → Release Factory → event brokers → DB Store ══
              alignItems is "flex-start" so the LEFT columns (all natural height = ROW1_H)
              stay at the top of the row even when the MiddleSection grows taller to
              accommodate the VAT Fraud Detection Agent stacked under the Tax Officer.
              With center alignment the LEFT side would shift downward by
              (Heff - ROW1_H) / 2 and break alignment with MiddleSection's absolute
              children. */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0 }}>

            {/* Entry Broker — vertically centered on yRT (= ROW1_H/2) so it
                lines up with the RT_Score output broker on the same horizontal. */}
            <div style={{ height: ROW1_H, display: 'flex', alignItems: 'center' }}>
              <Zone label="Entry">
                <BrokerNode label="Sales-order Event" topicKey="SALES_ORDER"
                  count={ev.sales_order_event} queueSize={q.sales_order_event} sm />
              </Zone>
            </div>

            {/* FanOut: solid grey → Sales Order Validation + Real-Time Risk
                Assessment | dashed grey → Goods Transport (the spine segment
                between Real-Time Risk Assessment and Goods Transport is
                dashed too) */}
            <FanOutMixedSVG height={ROW1_H} width={48} targets={[
              { y: yOV, dashed: false },
              { y: yRT, dashed: false },
              { y: yAN, dashed: true  },
            ]} />

            {/* Three parallel zones stacked — all at ZONE_W so Row 1 is visually aligned */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>

              <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
                <Zone label="Sales Order Validation" style={{ width: ZONE_W, boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                    <FactoryNode icon="✅" label="Sales Order Validation"
                      description="3–5 s · unlimited concurrency" sm width={SIDE_FACTORY_W}
                      tooltip="Sales Order Validation Factory — async per-order task with uniform 3–5 s delay. Emits ORDER_VALIDATION events." />
                  </div>
                </Zone>
              </div>

              <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
                <Zone label="Real-Time Risk Assessment" style={{ width: ZONE_W, height: '100%', boxSizing: 'border-box' }}>
                  {/* The inner content was visually biased toward the bottom of
                      the zone (large gap above the boxes, small gap below). A
                      small upward translate balances the gap on either side
                      without affecting layout — the children stay centered on
                      their flex row, the whole row just shifts up by 18 px. */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 0, height: '100%', justifyContent: 'flex-end', transform: 'translateY(-18px)' }}>
                    {/* Entry fan-out — mirrors the fan-in on the right */}
                    <FanOutSVG height={RT_STACK_H} targetYs={[rtTopY, rtBotY]} width={24} />
                    {/* Stacked RT1 + RT2 rows */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: RT_ROW_GAP }}>
                      <div style={{ height: RT_ROW_H, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <FactoryNode icon="⚖️" label="RT Risk As. 1" description="VAT ratio deviation" sm
                          tooltip="RT Risk Assessment 1 — flags transactions whose VAT-to-value ratio deviates from the supplier's historical baseline." />
                        <Arrow />
                        <BrokerNode label="RT Risk 1 Outcome" topicKey="RT_RISK_1_OUTCOME"
                          count={ev.rt_risk_1_outcome} sm
                          tooltip="RT_RISK_1_OUTCOME — one event per transaction with the VAT-ratio flag result.">
                          <FlaggedBadge flagged={rf.rt_risk_1_flagged} total={ev.rt_risk_1_outcome} />
                        </BrokerNode>
                      </div>
                      <div style={{ height: RT_ROW_H, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <FactoryNode icon="🔍" label="RT Risk As. 2" description="Watchlist lookup" sm
                          tooltip="RT Risk Assessment 2 — flags transactions whose seller or route appears on the active watchlist." />
                        <Arrow />
                        <BrokerNode label="RT Risk 2 Outcome" topicKey="RT_RISK_2_OUTCOME"
                          count={ev.rt_risk_2_outcome} sm
                          tooltip="RT_RISK_2_OUTCOME — one event per transaction with the watchlist lookup result.">
                          <FlaggedBadge flagged={rf.rt_risk_2_flagged} total={ev.rt_risk_2_outcome} />
                        </BrokerNode>
                      </div>
                    </div>
                    {/* FanIn: 2 rows → Risk Score Consolidation */}
                    <FanInSVG height={RT_STACK_H} inputYs={[rtTopY, rtBotY]} outputY={rtOutY} width={36} />
                    {/* Risk Score Consolidation — horizontally to the right of the two assessment rows */}
                    <FactoryNode icon="🔄" label="Risk Score Consolidation" description="GREEN / AMBER / RED" sm
                      tooltip="Risk Score Consolidation — combines RT1 + RT2 into a single risk score: GREEN (none flagged), AMBER (one), RED (both)." />
                  </div>
                </Zone>
              </div>

              <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
                <Zone label="Goods Transport" style={{ width: ZONE_W, boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                    <FactoryNode icon="🚢" label="Goods Transport"
                      description="exp. delay ~60 s · unlimited concurrency" sm width={SIDE_FACTORY_W}
                      tooltip="Goods Transport / Arrival Notification — async per-order task with exponential-delay arrival (~60 s mean). Emits ARRIVAL_NOTIFICATION events." />
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
                <BrokerNode label="Sales Order Validation" topicKey="ORDER_VALIDATION"
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
                <BrokerNode label="Goods Arrival Notification" topicKey="ARRIVAL_NOTIFICATION"
                  count={ev.arrival_notification} sm width={OUT_BROKER_W}
                  tooltip="ARRIVAL_NOTIFICATION — emitted once goods arrive at destination. Required by the Release Factory." />
              </div>
            </div>

            {/* Fan-in: 3 output brokers → Release Factory */}
            <FanInSVG height={ROW1_H} inputYs={[yOV, yRT, yAN]} outputY={ROW1_H / 2} width={60} />

            {/* Release Factory — vertically centered at ROW1_H/2 to line up with the fan-in output */}
            <div style={{ height: ROW1_H, display: 'flex', alignItems: 'center' }}>
              <FactoryNode icon="🎯" label="Release Factory" description="routes by score + validation" sm
                tooltip="Release Factory — waits for RT Score + Sales Order Validation + Goods Arrival Notification on each transaction, then routes: GREEN→Release, RED→Retain, AMBER→Investigate." />
            </div>

            {/* Fan-out: Release Factory → 3 event brokers.
                Target Ys match row-1 output brokers (yOV, yRT, yAN) so vertical spacing is consistent. */}
            <FanOutSVG height={ROW1_H} targetYs={[yOV, yRT, yAN]} width={48} />

            {/* Three event brokers — heights match row-1 zones so centers land at yOV / yRT / yAN */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: LGAP }}>
              <div style={{ height: OV_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Sales Order Release" topicKey="AUTOMATED_RELEASE"
                  count={ev.release_event} accent="#1f7a3c" sm width={OUT_BROKER_W}
                  tooltip="Sales Order Release — GREEN-path transactions cleared for storage without further investigation." />
              </div>
              <div style={{ height: RT_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Sales Order Retained" topicKey="AUTOMATED_RETAIN"
                  count={ev.retain_event} accent="#c0392b" sm width={OUT_BROKER_W}
                  tooltip="Sales Order Retained — RED-path transactions stored with the suspicious flag set." />
              </div>
              <div style={{ height: AN_H, display: 'flex', alignItems: 'center' }}>
                <BrokerNode label="Sales Order for Investigation" topicKey="INVESTIGATION_NOTIFICATION"
                  count={ev.investigate_event} accent="#e6820a" sm width={OUT_BROKER_W}
                  tooltip="Sales Order for Investigation — AMBER-path transactions handed off to the investigation sub-pipeline." />
              </div>
            </div>

            {/* Middle section: DB Store Factory + Hub (grouped in a dashed zone) + After-Inv
                brokers (mirroring event brokers) + the two-entity bottom band: Customs Office
                row above, Tax Office row + VAT Fraud Detection Agent below. Absolute-positioned
                canvas sized so the band extends below ROW1_H to fit both rows. */}
            <MiddleSection ev={ev} rf={rf} customs={customs} tax={tax} taxRunning={taxRunning}
              stored={stored} newStored={newStored}
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

        {/* Sub-box accent colors carried by the broker inner sub-boxes */}
        <LegendItem color="#1f7a3c" bg="#e8f5e9" label="Release (automated + post inv.)" />
        <LegendItem color="#c0392b" bg="#fde8e8" label="Retain (automated + post inv.)" />
        <LegendItem color="#e6820a" bg="#fff3e0" label="Investigation notification" />
        <LegendItem color="#6366f1" bg="#eef2ff" label="Revenue Guardian UI (operator)" />
        {/* Connector / arrow coding — all line strokes are neutral grey;
            only the dashed style remains as a semantic differentiator. */}
        <LegendItem color="#adb5bd" bg="#f8f9fa" label="Goods Transport / Arrival (dashed)" dashed />

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
  { key: 'order_validation',                    label: 'Sales Order Validation',           factory: 'Sales Order Validation Factory',     color: '#1f7a3c' },
  { key: 'rt_risk_1_outcome',                   label: 'RT Risk 1 Outcome',                factory: 'Real-Time Risk Assessment 1',        color: '#6f42c1' },
  { key: 'rt_risk_2_outcome',                   label: 'RT Risk 2 Outcome',                factory: 'Real-Time Risk Assessment 2',        color: '#6f42c1' },
  { key: 'rt_score',                            label: 'RT Score',                         factory: 'Risk Score Consolidation Factory',    color: '#e6820a' },
  { key: 'arrival_notification',                label: 'Goods Arrival Notification',       factory: 'Goods Transport Factory',             color: '#e67e22' },
  { key: 'release_event',                       label: 'Sales Order Release',              factory: 'Release Factory (GREEN)',             color: '#1f7a3c' },
  { key: 'retain_event',                        label: 'Sales Order Retained',             factory: 'Retain Factory (RED)',                color: '#c0392b' },
  { key: 'investigate_event',                   label: 'Sales Order for Investigation',    factory: 'Investigate Dispatch Factory (AMBER)', color: '#e6820a' },
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
  const [presentationMode, setPresentationMode] = useState(false)
  // Ref so the SSE callback always sees the latest value without re-subscribing.
  const presentationRef = useRef(false)
  useEffect(() => { presentationRef.current = presentationMode }, [presentationMode])
  const lastFrameRef = useRef(0)

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
        // Presentation mode: skip frames that arrive within 500 ms of the
        // last accepted frame. Reduces rendering load during screen-sharing.
        if (presentationRef.current) {
          const now = Date.now()
          if (now - lastFrameRef.current < 500) return
          lastFrameRef.current = now
        }
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

  // Sync the top scrollbar spacer width with the pipeline content width
  // so both scrollbars have the same range.
  const pipelineRef = useRef(null)
  useEffect(() => {
    const syncWidth = () => {
      const el = pipelineRef.current
      if (!el) return
      const spacer = el.previousElementSibling?.querySelector('.pipeline-scroll-spacer')
      if (spacer) spacer.style.width = el.scrollWidth + 'px'
    }
    syncWidth()
    const id = setInterval(syncWidth, 1000)
    return () => clearInterval(id)
  })

  return (
    <div className="page-container">
      {/* Title row — flex so the Revenue Guardian launcher can sit on the
          far right while the title + subtitle stay left-aligned. */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div className="page-title">Simulation</div>
          <div className="page-subtitle">
            Control the simulation and monitor the pub/sub pipeline in real time
          </div>
        </div>
        <a
          href="http://localhost:8080"
          target="_blank"
          rel="noopener noreferrer"
          title="Open the Revenue Guardian operator console (port 8080) in a new tab"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#6366f1', color: '#fff',
            border: 'none', borderRadius: 'var(--radius)',
            padding: '8px 14px', fontSize: 12, fontWeight: 700,
            textDecoration: 'none', whiteSpace: 'nowrap',
            boxShadow: '0 1px 4px rgba(99, 102, 241, 0.25)',
            cursor: 'pointer', flex: '0 0 auto',
          }}>
          🧑‍💼 Open Revenue Guardian
          <span style={{ fontSize: 11, opacity: 0.85 }}>↗</span>
        </a>
        <button
          onClick={() => setPresentationMode(p => !p)}
          title="Reduce UI refresh rate to 2 fps for smooth screen-sharing"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: presentationMode ? '#059669' : '#64748b',
            color: '#fff',
            border: 'none', borderRadius: 'var(--radius)',
            padding: '8px 14px', fontSize: 12, fontWeight: 700,
            cursor: 'pointer', flex: '0 0 auto',
            whiteSpace: 'nowrap',
            boxShadow: presentationMode ? '0 1px 4px rgba(5,150,105,0.3)' : 'none',
          }}>
          🖥 Presentation {presentationMode ? 'ON' : 'OFF'}
        </button>
      </div>

      <SimControls status={status} onRefresh={() => { refreshStatus(); refreshPipeline() }} />
      <KpiStrip pipeline={pipeline} />
      <PipelineDiagram pipeline={pipeline} status={status} />
      <EventCountsTable pipeline={pipeline} />
    </div>
  )
}
