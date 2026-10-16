import { useEffect, useState } from 'react'
import { api, getToken, setToken } from './api.js'
import { Column, ColumnProvider, go, useColumn, useRoute } from './ui.jsx'
import Ask from './pages/Ask.jsx'
import Review from './pages/Review.jsx'
import Memory from './pages/Memory.jsx'
import People from './pages/People.jsx'
import Plan from './pages/Plan.jsx'
import Trace from './pages/Trace.jsx'
import Sources from './pages/Sources.jsx'
import GraphPage from './pages/Graph.jsx'

const NAV = [
  ['ask', 'Ask', Ask], ['review', 'Review', Review], ['memory', 'Memory', Memory], ['people', 'People', People],
  ['plan', 'Plan', Plan], ['trace', 'Trace', Trace], ['sources', 'Sources', Sources], ['map', 'Map', GraphPage],
]

function Shell() {
  const { page, q } = useRoute()
  const col = useColumn()
  const [org, setOrg] = useState(null)
  const [tok, setTok] = useState(getToken())
  const [showTok, setShowTok] = useState(false)
  useEffect(() => { api.overview().then((o) => setOrg(o.organization)).catch(() => {}) }, [])
  useEffect(() => { col.close() }, [page]) // eslint-disable-line react-hooks/exhaustive-deps
  const Current = (NAV.find(([k]) => k === page) || NAV[0])[2]
  const wide = ['people', 'map', 'sources', 'trace'].includes(page)
  return (
    <div className="app">
      <header className="top">
        <div className="brand">Gitwhy<small>why your code is the way it is</small></div>
        <nav className="nav" aria-label="Main">
          {NAV.slice(0, 5).map(([k, l]) => <a key={k} href={`#/${k}`} className={page === k ? 'on' : ''}>{l}</a>)}
          <span className="gap" />
          {NAV.slice(5).map(([k, l]) => <a key={k} href={`#/${k}`} className={page === k ? 'on' : ''}>{l}</a>)}
        </nav>
        {org && <span className="org">{org.name}{org.is_synthetic ? ' (synthetic)' : ''}</span>}
        <button className="btn quiet small" onClick={() => setShowTok((s) => !s)} aria-label="Demo token" title="Demo token (only if the server asks for one)">⚿</button>
        {showTok && <input type="password" value={tok} placeholder="demo token" style={{ width: 150 }} aria-label="Demo token"
          onChange={(e) => { setTok(e.target.value); setToken(e.target.value) }} />}
      </header>
      <div className={`work${col.sel ? ' open' : ''}`}>
        <main className={`surface${wide ? ' wide' : ''}`}><div className="wrap"><Current q={q} /></div></main>
        <Column go={go} />
      </div>
    </div>
  )
}
export default function App() { return <ColumnProvider><Shell /></ColumnProvider> }
