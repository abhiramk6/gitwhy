import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading, Tags, ago, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const LABEL = { commit: 'commit', pull_request: 'pull request', discussion: 'review thread', ticket: 'ticket', decision: 'decision' }

export default function Trace({ q }) {
  const files = useAsync(api.files)
  const col = useColumn()
  const [filter, setFilter] = useState('')
  const [sel, setSel] = useState(q.get('f') || '')
  const [picking, setPicking] = useState(!q.get('f'))
  const [t, setT] = useState(null)
  const [ex, setEx] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    if (!sel) return
    const [repo, ...rest] = sel.split(':')
    const path = rest.join(':')
    setT(null); setEx(null); setErr(null)
    api.trace(repo, path).then(setT).catch(setErr)
    api.explainTrace(repo, path).then(setEx).catch((e) => setEx({ status: 'error', note: e.message }))
  }, [sel])
  const shown = (files.data || []).filter((f) => f.id.toLowerCase().includes(filter.toLowerCase())).slice(0, 40)
  const s = t?.profile?.style
  return (
    <div className="stack">
      <div><h1>Pick a file. We'll show its story, not its diff.</h1>
        <p className="lede">Why it looks the way it does, from the commits, pull requests, review threads, tickets and decisions that shaped it.</p></div>
      <div>
        <div className="picker">
          <code style={{ background: 'none', fontSize: 15 }}>{sel ? sel.replace(':', ' / ') : 'No file chosen'}</code>
          <button className="btn quiet small" onClick={() => setPicking((p) => !p)}>{picking ? 'Close' : 'Change file'}</button>
        </div>
        {picking && (
          <div className="pop">
            <input type="search" placeholder="Search files" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search files" />
            <ul className="list" style={{ marginTop: 8 }}>{shown.map((f) => <li key={f.id}><button onClick={() => { setSel(f.id); setPicking(false) }}><code style={{ background: 'none' }}>{f.id.replace(':', ' / ')}</code></button></li>)}</ul>
          </div>
        )}
      </div>
      {err && <Problem error={err} />}
      {sel && !ex && <Reading>Reading the history of this file</Reading>}
      {ex?.status === 'ok' && (
        <div className="stack-s">
          {ex.headline && <p className="headline"><Hl text={ex.headline.text} k={ex.headline.key} /></p>}
          <div className="answer">{ex.points.slice(0, 3).map((p, i) => <p key={i}><Hl text={p.text} k={p.key} /> <Tags ids={p.cites} /></p>)}</div>
        </div>
      )}
      {ex && ex.status !== 'ok' && <p className="notice">{ex.status === 'llm_required' || ex.status === 'error' ? 'The write-up is down; search still works. Try again shortly. The history is below.' : 'There is too little history to say more than what is listed below.'}</p>}
      {t && (
        <details className="evidence" open={ex && ex.status !== 'ok'}><summary>Show the evidence ({t.events.length})</summary>
          {s && s.functions > 0 && <p className="small muted" style={{ marginBottom: 16 }}>{s.functions} functions, {s.classes} classes; {s.args_annotated} of {s.args_total} arguments and {s.returns_annotated} of {s.functions} return values annotated; {s.with_docstring} with a docstring; {s.comment_lines} comment lines.{t.url && <> <a href={t.url} target="_blank" rel="noreferrer">Open the file</a></>}</p>}
          <ul className="core">
            {t.events.map((e, i) => (
              <li key={i}>
                <div className="when">{e.when ? ago(e.when) : 'undated'}{e.who ? ` · ${shortName(e.who)}` : ''} · {LABEL[e.kind]} {e.ref}</div>
                <button className="what" style={{ background: 'none', border: 0, padding: 0, textAlign: 'left', cursor: 'pointer', color: 'inherit', font: 'inherit', fontWeight: 500 }} onClick={() => col.open({ id: e.id, label: e.title })}>{e.title}</button>
                {e.kind === 'discussion' && <div className="small muted" style={{ marginTop: 4 }}>{(e.body || '').slice(0, 220)}</div>}
              </li>
            ))}
          </ul></details>
      )}
    </div>
  )
}
