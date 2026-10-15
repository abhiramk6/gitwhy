import { useEffect, useState } from 'react'
import Overview from './pages/Overview.jsx'
import GraphPage from './pages/Graph.jsx'
import Planner from './pages/Planner.jsx'
import Knowledge from './pages/Knowledge.jsx'
import { getToken, setToken } from './api.js'

const PAGES = [
  ['overview', 'Overview', Overview],
  ['graph', 'Graph', GraphPage],
  ['planner', 'Feature Planner', Planner],
  ['knowledge', 'Knowledge', Knowledge],
]

function useHash() {
  const read = () => (window.location.hash.replace('#/', '') || 'overview').split('?')[0]
  const [page, setPage] = useState(read)
  useEffect(() => {
    const on = () => setPage(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return page
}

export default function App() {
  const page = useHash()
  const [token, setTok] = useState(getToken())
  const Current = (PAGES.find(([k]) => k === page) || PAGES[0])[2]
  return (
    <div className="shell">
      <nav aria-label="Main">
        <div className="brand">LORE<span>Intelligence</span></div>
        {PAGES.map(([k, label]) => (
          <a key={k} href={`#/${k}`} className={page === k ? 'on' : ''}>{label}</a>
        ))}
        <div className="spacer" />
        <label className="token">
          Demo token
          <input type="password" value={token} placeholder="only if required"
                 onChange={(e) => { setTok(e.target.value); setToken(e.target.value) }} />
        </label>
        <p className="note">Synthetic organization. No real people or customer data.</p>
      </nav>
      <main><Current /></main>
    </div>
  )
}
