import { NavLink } from 'react-router-dom'
import SimulationWidget from './SimulationWidget'

export default function EclLayout({ children }) {
  return (
    <>
      {/* EC institutional top strip */}
      <div className="ec-top-strip">
        <svg width="28" height="20" viewBox="0 0 28 20" aria-hidden="true">
          <rect width="28" height="20" fill="#003399"/>
          {/* EU flag stars (simplified) */}
          {[...Array(12)].map((_, i) => {
            const angle = (i * 30 - 90) * Math.PI / 180
            const cx = 14 + 6 * Math.cos(angle)
            const cy = 10 + 6 * Math.sin(angle)
            return <text key={i} x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
                         fontSize="3.5" fill="#FFED00">★</text>
          })}
        </svg>
        <span className="ec-commission">European Commission</span>
        <span className="ec-separator">|</span>
        <span>Taxation and Customs Union</span>
      </div>

      {/* Site header */}
      <header className="site-header">
        <NavLink to="/" className="site-header__title">
          <span style={{ fontSize: 28 }}>🇪🇺</span>
          <div>
            <h1>European Custom Data Hub</h1>
            <span>Real-Time Transaction Monitoring</span>
          </div>
        </NavLink>

        {/* Simulation widget — top-right of header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', whiteSpace: 'nowrap' }}>
            March 2026 simulation
          </span>
          <SimulationWidget />
        </div>
      </header>

      {/* Navigation */}
      <nav className="site-nav">
        <NavLink to="/"           className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                 end>Main</NavLink>
        <NavLink to="/dashboard"  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Dashboard
        </NavLink>
        <NavLink to="/suspicious" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Suspicious Transactions
        </NavLink>
      </nav>

      {/* Page content */}
      <main>
        {children}
      </main>

      <footer className="site-footer">
        © European Commission — European Custom Data Hub — Real-Time Demo
      </footer>
    </>
  )
}
