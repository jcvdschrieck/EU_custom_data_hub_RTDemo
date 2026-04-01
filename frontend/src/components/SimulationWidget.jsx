import { useState, useEffect, useCallback } from 'react'
import { getSimStatus, simStart, simPause, simResume, simReset, simSetSpeed } from '../api'

const SPEEDS = [
  { label: '30×',   value: 30 },
  { label: '120×',  value: 120 },
  { label: '360×',  value: 360 },
  { label: '1440×', value: 1440 },
]

export default function SimulationWidget() {
  const [status, setStatus] = useState(null)

  const refresh = useCallback(async () => {
    try { setStatus(await getSimStatus()) } catch { /* API not ready yet */ }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [refresh])

  if (!status) return (
    <div className="sim-widget">
      <span className="sim-dot stopped" />
      <span style={{ opacity: 0.6 }}>Connecting…</span>
    </div>
  )

  const { running, finished, pct_complete, speed, sim_time, fired_count, total } = status
  const dotClass = finished ? 'finished' : running ? 'running' : 'paused'
  const label    = finished ? 'Done' : running ? 'Live' : fired_count ? 'Paused' : 'Ready'
  const simDate  = sim_time ? sim_time.slice(0, 10) : '—'

  const handleToggle = async () => {
    if (finished) return
    if (running)  await simPause()
    else if (fired_count) await simResume()
    else          await simStart()
    refresh()
  }

  const handleReset = async () => { await simReset(); refresh() }

  const handleSpeed = async (e) => {
    await simSetSpeed(parseFloat(e.target.value))
    refresh()
  }

  return (
    <div className="sim-widget">
      <div className="sim-status-group" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className={`sim-dot ${dotClass}`} />
        <span style={{ fontSize: 11, opacity: 0.85 }}>{label}</span>
      </div>

      <div className="sim-progress-bar" title={`${pct_complete?.toFixed(1)}%`}>
        <div className="sim-progress-bar__fill" style={{ width: `${pct_complete || 0}%` }} />
      </div>

      <span style={{ fontSize: 10, opacity: 0.7, whiteSpace: 'nowrap' }}>
        {simDate} · {fired_count}/{total}
      </span>

      <select className="sim-speed" value={speed} onChange={handleSpeed} title="Simulation speed">
        {SPEEDS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>

      <button
        className={`sim-btn ${!running && !finished ? 'primary' : ''}`}
        onClick={handleToggle}
        disabled={finished}
        title={running ? 'Pause' : 'Start / Resume'}
      >
        {running ? '⏸' : '▶'}
      </button>

      <button className="sim-btn" onClick={handleReset} title="Reset simulation">↺</button>
    </div>
  )
}
