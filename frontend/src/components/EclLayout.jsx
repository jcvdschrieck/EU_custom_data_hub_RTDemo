import { NavLink } from 'react-router-dom'
import SimulationWidget from './SimulationWidget'

const EU_COUNTRY_QUEUES = [
  { code: 'none', name: '— Go to country —', url: null },
  { code: 'AT', flag: '🇦🇹', name: 'Austria',        url: null },
  { code: 'BE', flag: '🇧🇪', name: 'Belgium',         url: null },
  { code: 'BG', flag: '🇧🇬', name: 'Bulgaria',        url: null },
  { code: 'HR', flag: '🇭🇷', name: 'Croatia',         url: null },
  { code: 'CY', flag: '🇨🇾', name: 'Cyprus',          url: null },
  { code: 'CZ', flag: '🇨🇿', name: 'Czech Republic',  url: null },
  { code: 'DK', flag: '🇩🇰', name: 'Denmark',         url: null },
  { code: 'EE', flag: '🇪🇪', name: 'Estonia',         url: null },
  { code: 'FI', flag: '🇫🇮', name: 'Finland',         url: null },
  { code: 'FR', flag: '🇫🇷', name: 'France',          url: null },
  { code: 'DE', flag: '🇩🇪', name: 'Germany',         url: null },
  { code: 'GR', flag: '🇬🇷', name: 'Greece',          url: null },
  { code: 'HU', flag: '🇭🇺', name: 'Hungary',         url: null },
  { code: 'IE', flag: '🇮🇪', name: 'Ireland',         url: '/ireland-app/' },
  { code: 'IT', flag: '🇮🇹', name: 'Italy',           url: null },
  { code: 'LV', flag: '🇱🇻', name: 'Latvia',          url: null },
  { code: 'LT', flag: '🇱🇹', name: 'Lithuania',       url: null },
  { code: 'LU', flag: '🇱🇺', name: 'Luxembourg',      url: null },
  { code: 'MT', flag: '🇲🇹', name: 'Malta',           url: null },
  { code: 'NL', flag: '🇳🇱', name: 'Netherlands',     url: null },
  { code: 'PL', flag: '🇵🇱', name: 'Poland',          url: null },
  { code: 'PT', flag: '🇵🇹', name: 'Portugal',        url: null },
  { code: 'RO', flag: '🇷🇴', name: 'Romania',         url: null },
  { code: 'SK', flag: '🇸🇰', name: 'Slovakia',        url: null },
  { code: 'SI', flag: '🇸🇮', name: 'Slovenia',        url: null },
  { code: 'ES', flag: '🇪🇸', name: 'Spain',           url: null },
  { code: 'SE', flag: '🇸🇪', name: 'Sweden',          url: null },
]

function CountryQueueDropdown() {
  const handleChange = (e) => {
    const code = e.target.value
    if (code === 'none') return
    const country = EU_COUNTRY_QUEUES.find(c => c.code === code)
    if (country?.url) {
      window.open(country.url, '_blank', 'noreferrer')
    } else {
      alert(`${country?.flag ?? ''} ${country?.name ?? code} — investigation queue not available in this demo.`)
    }
    e.target.value = 'none'
  }

  return (
    <select
      onChange={handleChange}
      defaultValue="none"
      className="nav-link"
      style={{
        background: 'transparent',
        color: 'rgba(255,255,255,0.85)',
        border: 'none',
        cursor: 'pointer',
        fontSize: 13,
        fontWeight: 600,
        padding: '0 4px',
        appearance: 'auto',
        outline: 'none',
      }}
    >
      {EU_COUNTRY_QUEUES.map(c => (
        <option
          key={c.code}
          value={c.code}
          style={{ background: '#003399', color: '#fff' }}
        >
          {c.code === 'none' ? c.name : `${c.flag} ${c.name}${c.url ? ' ↗' : ''}`}
        </option>
      ))}
    </select>
  )
}

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
        <NavLink to="/main"       className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Main
        </NavLink>
        <NavLink to="/dashboard"  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Dashboard
        </NavLink>
        <NavLink to="/suspicious" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Suspicious Transactions
        </NavLink>
        <NavLink to="/agent-log"  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Agent Log
        </NavLink>
        <NavLink to="/simulation" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          Simulation
        </NavLink>
        <CountryQueueDropdown />
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
