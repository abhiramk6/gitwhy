import { useEffect, useRef, useState } from 'react'
import { api, setOrg } from '../api.js'

const STEPS = ['Organization', 'GitHub', 'Jira', 'Reading']

function Steps({ at }) {
  return <ol className="steps" aria-label="Progress">{STEPS.map((s, i) => <li key={s} className={i === at ? 'on' : i < at ? 'done' : ''}><span>{i + 1}</span>{s}</li>)}</ol>
}

function Check({ items, picked, onToggle, label }) {
  return (
    <ul className="checks" aria-label={label}>
      {items.map((it) => (
        <li key={it.id}><label><input type="checkbox" checked={picked.includes(it.id)} onChange={() => onToggle(it.id)} />
          <span><b style={{ fontWeight: 500 }}>{it.title}</b>{it.meta && <span className="small muted"> · {it.meta}</span>}</span></label></li>
      ))}
    </ul>
  )
}

const DOT = { done: '', running: 'inferred', failed: 'contradicted', pending: 'pending', skipped: 'pending' }

function SyncView({ slug, onDone, onBack }) {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState(null)
  const timer = useRef(null)
  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const s = await api.syncStatus(slug); if (!live) return
        setSt(s)
        if (s.job?.status === 'running') timer.current = setTimeout(tick, 2000)
      } catch (e) { if (live) { setErr(e.message); timer.current = setTimeout(tick, 4000) } }
    }
    tick()
    return () => { live = false; clearTimeout(timer.current) }
  }, [slug])
  const job = st?.job
  const done = job?.status === 'succeeded'
  return (
    <div className="stack">
      <div>
        <h1>{done ? 'Everything is read.' : job?.status === 'failed' ? 'We could not finish.' : 'Reading your organization.'}</h1>
        <p className="lede">{done ? 'Your answers now come from your own history.' : job?.status === 'failed' ? 'Nothing was lost; fix the problem and start again.' : 'This takes a few minutes. You can leave this page open; progress is saved.'}</p>
      </div>
      {err && <p className="notice err">{err}</p>}
      <ul className="stages" aria-live="polite">
        {(job?.stages || []).map((s) => (
          <li key={s.key} className={s.state}>
            <span className={`dot ${DOT[s.state] || ''}`} />
            <div><div style={{ fontWeight: 500 }}>{s.label}{s.state === 'skipped' ? ' (skipped)' : ''}</div>
              <div className="small muted">{s.detail || (s.state === 'pending' ? 'Waiting' : '')}</div></div>
            <span className="small muted">{s.state === 'done' ? 'Done' : s.state === 'running' ? 'Working' : s.state === 'failed' ? 'Failed' : ''}</span>
          </li>
        ))}
      </ul>
      {job?.error && <p className="notice err" role="alert">{job.error}</p>}
      <div className="row">
        {done && <button className="btn" onClick={onDone}>Open {st.organization.name}</button>}
        {job?.status === 'failed' && <button className="btn" onClick={onBack}>Back to connections</button>}
      </div>
    </div>
  )
}

export default function Onboarding({ me, initial, onReady, onCancel }) {
  const [step, setStep] = useState(initial?.slug ? (initial.status === 'syncing' ? 3 : 1) : 0)
  const [org, setOrgState] = useState(initial?.slug ? initial : null)
  const [name, setName] = useState('')
  const [gh, setGh] = useState({ token: '', owner: '', repos: [], picked: [], checked: false })
  const [jr, setJr] = useState({ site: '', email: '', token: '', projects: [], picked: [], checked: false })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn) => { setBusy(true); setErr(null); try { await fn() } catch (e) { setErr(e.message) } finally { setBusy(false) } }
  const toggle = (set, key) => (id) => set((s) => ({ ...s, [key]: s[key].includes(id) ? s[key].filter((x) => x !== id) : [...s[key], id] }))
  const create = () => run(async () => { const o = await api.createOrg(name.trim()); setOrgState(o); setOrg(o.slug); setStep(1) })
  const checkGh = () => run(async () => { const r = await api.testGithub(gh.token, gh.owner); setGh((g) => ({ ...g, repos: r.repos, checked: true, login: r.login })) })
  const checkJr = () => run(async () => { const r = await api.testJira(jr.site, jr.email, jr.token); setJr((j) => ({ ...j, projects: r.projects, checked: true })) })
  const start = () => run(async () => {
    await api.saveConnections(org.slug, { github_token: gh.token, repos: gh.picked, jira_site: jr.picked.length ? jr.site : '', jira_email: jr.email,
      jira_token: jr.token, jira_projects: jr.picked })
    await api.startSync(org.slug); setStep(3)
  })
  const nothing = gh.picked.length === 0 && jr.picked.length === 0
  return (
    <main className="welcome onboard">
      <div className="welcome-in stack">
        <div className="row" style={{ justifyContent: 'space-between' }}><div className="brand" style={{ fontSize: 22 }}>Gitwhy</div>
          {onCancel && step < 3 && <button className="btn quiet small" onClick={onCancel}>Cancel</button>}</div>
        <Steps at={step} />
        {err && <p className="notice err" role="alert">{err}</p>}

        {step === 0 && (
          <div className="stack">
            <div><h1>Name your organization.</h1><p className="lede">This is the space your team's questions and answers live in.</p></div>
            <label className="sr" htmlFor="org">Organization name</label>
            <input id="org" type="text" placeholder="Acme Robotics" value={name} onChange={(e) => setName(e.target.value)} />
            <div className="row"><button className="btn" disabled={busy || name.trim().length < 2} onClick={create}>Continue</button></div>
          </div>
        )}

        {step === 1 && (
          <div className="stack">
            <div><h1>Connect GitHub.</h1><p className="lede">Gitwhy only reads. Create a token that can read the repositories you choose (contents, pull requests, issues). It is stored on the server, never in the database or the browser.</p></div>
            <label className="sr" htmlFor="ght">GitHub token</label>
            <input id="ght" type="password" placeholder="GitHub token (ghp_… or github_pat_…)" value={gh.token} onChange={(e) => setGh({ ...gh, token: e.target.value, checked: false })} autoComplete="off" />
            <label className="sr" htmlFor="gho">Organization or user</label>
            <input id="gho" type="text" placeholder="GitHub organization or username (optional)" value={gh.owner} onChange={(e) => setGh({ ...gh, owner: e.target.value, checked: false })} />
            <div className="row"><button className="btn quiet" disabled={busy || gh.token.length < 10} onClick={checkGh}>{gh.checked ? 'Check again' : 'Check token and list repositories'}</button></div>
            {gh.checked && (gh.repos.length === 0 ? <p className="notice">This token sees no repositories there.</p> : (
              <div className="stack-s"><p className="small muted">Signed in as {gh.login}. Choose up to 25 repositories ({gh.picked.length} chosen).</p>
                <Check label="Repositories" items={gh.repos.map((r) => ({ id: r.full_name, title: r.full_name, meta: [r.private ? 'private' : 'public', r.language, r.pushed_at && `pushed ${r.pushed_at}`].filter(Boolean).join(' · ') }))}
                  picked={gh.picked} onToggle={toggle(setGh, 'picked')} /></div>))}
            <div className="row"><button className="btn" onClick={() => setStep(2)}>{gh.picked.length ? 'Continue' : 'Skip GitHub'}</button></div>
          </div>
        )}

        {step === 2 && (
          <div className="stack">
            <div><h1>Connect Jira.</h1><p className="lede">Optional. Tickets and their comments are linked to the pull requests that mention them. Use an Atlassian API token (read access).</p></div>
            <input type="text" placeholder="https://yourcompany.atlassian.net" value={jr.site} onChange={(e) => setJr({ ...jr, site: e.target.value, checked: false })} aria-label="Jira site" />
            <input type="text" placeholder="Atlassian account email" value={jr.email} onChange={(e) => setJr({ ...jr, email: e.target.value, checked: false })} aria-label="Atlassian email" />
            <input type="password" placeholder="Atlassian API token" value={jr.token} onChange={(e) => setJr({ ...jr, token: e.target.value, checked: false })} autoComplete="off" aria-label="Atlassian API token" />
            <div className="row"><button className="btn quiet" disabled={busy || !jr.site || !jr.email || jr.token.length < 6} onClick={checkJr}>{jr.checked ? 'Check again' : 'Check and list projects'}</button></div>
            {jr.checked && (jr.projects.length === 0 ? <p className="notice">No projects visible to this account.</p> :
              <Check label="Jira projects" items={jr.projects.map((p) => ({ id: p.key, title: `${p.key} · ${p.name}` }))} picked={jr.picked} onToggle={toggle(setJr, 'picked')} />)}
            <div className="notice small">Reading is done by the server. Pull requests, tickets and code are sent to the language models that write the answers (Gemini) and to the model that builds the search index (Voyage). Nothing is ever posted back to GitHub or Jira.</div>
            <div className="row"><button className="btn" disabled={busy || nothing} onClick={start}>Start reading</button>
              <button className="btn quiet" onClick={() => setStep(1)}>Back</button></div>
            {nothing && <p className="small muted">Choose at least one repository or Jira project.</p>}
          </div>
        )}

        {step === 3 && org && <SyncView slug={org.slug} onBack={() => setStep(1)} onDone={() => { setOrg(org.slug); onReady(org.slug) }} />}
      </div>
    </main>
  )
}
