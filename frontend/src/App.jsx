import { useEffect, useState } from 'react'
import product from '@product'
import { api, getOrg, getSession, getToken, setOrg, setSession, setToken } from './api.js'
import { Column, ColumnProvider, go, useColumn, useRoute } from './ui.jsx'
import Ask from './pages/Ask.jsx'
import Review from './pages/Review.jsx'
import Memory from './pages/Memory.jsx'
import People from './pages/People.jsx'
import Plan from './pages/Plan.jsx'
import Trace from './pages/Trace.jsx'
import Sources from './pages/Sources.jsx'
import Impact from './pages/Impact.jsx'
import Results from './pages/Results.jsx'
import GraphPage from './pages/Graph.jsx'
import Welcome from './pages/Welcome.jsx'
import Onboarding from './pages/Onboarding.jsx'

const NAV = [
  ['ask', 'Ask', Ask], ['review', 'Review', Review], ['memory', 'Memory', Memory], ['people', 'People', People],
  ['plan', 'Plan', Plan], ['impact', 'Impact', Impact], ['trace', 'Trace', Trace], ['sources', 'Sources', Sources], ['results', 'Results', Results], ['map', 'Map', GraphPage],
]
const NAV_SHOWN = ['ask', 'review', 'memory', 'people', 'plan', 'impact', 'trace', 'sources', 'results']

function Shell({ me, onSwitch, onSignOut }) {
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
        <div className="brand">{product.name}<small>{product.tagline}</small></div>
        <nav className="nav" aria-label="Main">
          {NAV.filter(([k]) => NAV_SHOWN.includes(k)).map(([k, l]) => <a key={k} href={`#/${k}`} className={page === k || (page === 'map' && k === 'sources') ? 'on' : ''}>{l}</a>)}
        </nav>
        {me ? (
          <>
            <select className="org-switch" aria-label="Organization" value={getOrg()} onChange={(e) => onSwitch(e.target.value)}>
              {me.organizations.map((o) => <option key={o.slug} value={o.slug}>{o.name}{o.status !== 'ready' ? ' (setting up)' : ''}</option>)}
              <option value="__new">New organization…</option>
            </select>
            <button className="btn quiet small" onClick={onSignOut}>Sign out</button>
          </>
        ) : (
          <>
            {org && <span className="org">{org.name}{org.is_synthetic ? ' (synthetic)' : ''}</span>}
            <button className="btn quiet small" onClick={() => setShowTok((s) => !s)} aria-label="Demo token" title="Demo token (only if the server asks for one)">⚿</button>
            {showTok && <input type="password" value={tok} placeholder="demo token" style={{ width: 150 }} aria-label="Demo token"
              onChange={(e) => { setTok(e.target.value); setToken(e.target.value) }} />}
          </>
        )}
      </header>
      <div className={`work${col.sel ? ' open' : ''}`}>
        <main className={`surface${wide ? ' wide' : ''}`}><div className="wrap"><Current q={q} /></div></main>
        <Column go={go} />
      </div>
    </div>
  )
}
function Gate() {
  const [meta, setMeta] = useState(null)
  const [me, setMe] = useState(null)
  const [session, setSess] = useState(getSession())
  const [loading, setLoading] = useState(true)
  const { page } = useRoute()
  const refresh = async () => {
    try { const r = await api.me(); setMe(r); return r } catch { setSession(''); setSess(''); setMe(null); return null }
  }
  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta({ auth: false })) }, [])
  useEffect(() => { if (meta?.auth && session) { setLoading(true); refresh().finally(() => setLoading(false)) } else setLoading(false) }, [meta, session]) // eslint-disable-line
  if (!meta || loading) return <main className="welcome"><div className="welcome-in"><div className="reading" role="status"><span className="sr">Loading</span><i /><i /><i /></div></div></main>
  if (!meta.auth) return <Shell />
  if (!session || !me) return <Welcome onSignedIn={(r) => { setSess(getSession()); setMe(r); if (!getOrg() && r.organizations[0]) setOrg(r.organizations[0].slug) }} />
  const orgs = me.organizations
  const cur = orgs.find((o) => o.slug === getOrg()) || orgs.find((o) => o.status === 'ready') || orgs[0]
  if (cur && cur.slug !== getOrg()) setOrg(cur.slug)
  const creating = page === 'onboarding' || !cur
  const unfinished = cur && cur.status !== 'ready'
  if (creating || unfinished) {
    return <Onboarding key={creating ? 'new' : cur.slug} me={me} initial={creating ? null : cur}
      onCancel={orgs.some((o) => o.status === 'ready') ? () => { window.location.hash = '#/ask'; refresh() } : null}
      onReady={async (slug) => { await refresh(); setOrg(slug); window.location.hash = '#/ask' }} />
  }
  return <Shell me={me}
    onSwitch={(slug) => { if (slug === '__new') { window.location.hash = '#/onboarding'; return } setOrg(slug); window.location.hash = '#/ask'; window.location.reload() }}
    onSignOut={() => { setSession(''); setOrg(''); setSess(''); setMe(null); window.location.hash = '#/ask' }} />
}

export default function App() { return <ColumnProvider><Gate /></ColumnProvider> }
