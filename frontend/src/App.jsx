import { useEffect, useState } from 'react'
import product from '@product'
import { api, getOrg, getSession, getToken, setOrg, setSession, setToken } from './api.js'
import { Column, ColumnProvider, LogoMark, go, useColumn, useRoute } from './ui.jsx'
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
  ['ask', 'Ask', Ask], ['review', 'Review a PR', Review], ['memory', 'Memory', Memory], ['people', 'People', People],
  ['plan', 'Plan a feature', Plan], ['impact', 'Change impact', Impact], ['trace', 'Trace a file', Trace], ['sources', 'Sources', Sources], ['results', 'Results', Results], ['map', 'Map', GraphPage],
]
const GROUPS = [['Work', ['ask', 'review', 'plan', 'impact']], ['Knowledge', ['memory', 'people', 'trace', 'sources']], ['Measure', ['results']]]
const ICONS = {
  ask: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  review: <><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="8" r="2.5" /><path d="M6 8.5v7M18 10.5c0 4-6 3-11 6" /></>,
  memory: <><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H19v15H5.5A1.5 1.5 0 0 0 4 20.5z" /><path d="M4 20.5A1.5 1.5 0 0 1 5.5 19H19v2H5.5" /></>,
  people: <><circle cx="9" cy="8" r="3.2" /><path d="M3 20c.5-3.5 3-5.5 6-5.5s5.5 2 6 5.5" /><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.8c1.8.7 3 2.4 3.3 5.2" /></>,
  trace: <><path d="M12 3v4M12 17v4M5 12h4M15 12h4" /><circle cx="12" cy="12" r="3" /></>,
  sources: <><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></>,
  plan: <><path d="M9 6h11M9 12h11M9 18h11" /><path d="m3.5 6 1.3 1.3L7 5M3.5 12l1.3 1.3L7 11M3.5 18l1.3 1.3L7 17" /></>,
  impact: <><circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6.5" /><circle cx="12" cy="12" r="10" /></>,
  results: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
}
const Icon = ({ name }) => <svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>
const initials = (s) => (s || '?').split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((x) => x[0].toUpperCase()).join('')

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
  const label = Object.fromEntries(NAV.map(([k, l]) => [k, l]))
  const orgName = org?.name || ''
  return (
    <div className="app">
      <aside className="side">
        <div className="brand"><LogoMark />
          <div><b>{product.name}</b><small>{product.tagline}</small></div></div>
        {me ? (
          <div className="org-card"><i>{initials(me.organizations.find((o) => o.slug === getOrg())?.name || '?')}</i>
            <select className="org-switch" aria-label="Organization" value={getOrg()} onChange={(e) => onSwitch(e.target.value)}>
              {me.organizations.map((o) => <option key={o.slug} value={o.slug}>{o.name}{o.status !== 'ready' ? ' (setting up)' : ''}</option>)}
              <option value="__new">New organization…</option>
            </select></div>
        ) : org && <div className="org-card"><i>{initials(orgName)}</i><span>{org.name}{org.is_synthetic ? ' (synthetic)' : ''}</span></div>}
        <nav className="nav" aria-label="Main">
          {GROUPS.map(([g, keys]) => (
            <div className="group" key={g}><h4>{g}</h4>
              {keys.map((k) => <a key={k} href={`#/${k}`} className={page === k || (page === 'map' && k === 'sources') ? 'on' : ''}><Icon name={k} />{label[k]}</a>)}
            </div>
          ))}
        </nav>
        <div className="me">
          {me ? (
            <>
              <div className="av">{initials(me.user?.name || me.user?.email)}</div>
              <div className="who"><div>{me.user?.name || me.user?.email}</div><small>{me.user?.email === 'demo@gitwhy.test' ? 'Read-only' : 'Signed in'}</small></div>
              <button className="btn quiet small" onClick={onSignOut}>Sign out</button>
            </>
          ) : (
            <>
              <button className="btn quiet small" onClick={() => setShowTok((s) => !s)} aria-label="Demo token" title="Demo token (only if the server asks for one)">⚿</button>
              {showTok && <input type="password" value={tok} placeholder="demo token" style={{ width: 130 }} aria-label="Demo token"
                onChange={(e) => { setTok(e.target.value); setToken(e.target.value) }} />}
            </>
          )}
        </div>
      </aside>
      <div className={`work${col.sel ? ' open' : ''}`}>
        <main className={`surface${wide ? ' wide' : ''}`}><div className="wrap"><div className="view" key={page}><Current q={q} /></div></div></main>
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
