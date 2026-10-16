import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading, Strata, Tags, TYPES, ago, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const KIND = { commit: 'github_commit', pull_request: 'github_pr', discussion: 'github_comment', ticket: 'jira_issue', decision: 'adr' }
const LABEL = { commit: 'commit', pull_request: 'pull request', discussion: 'review thread', ticket: 'ticket', decision: 'decision' }

export default function Trace({ q }) {
  const files = useAsync(api.files)
  const col = useColumn()
  const [filter, setFilter] = useState('')
  const [sel, setSel] = useState(q.get('f') || '')
  const [t, setT] = useState(null)
  const [ex, setEx] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    if (!sel) return
    const [repo, ...rest] = sel.split(':')
    setT(null); setEx(null); setErr(null)
    const path = rest.join(':')
    api.trace(repo, path).then(setT).catch(setErr)
    api.explainTrace(repo, path).then(setEx).catch((e) => setEx({ status: 'error', note: e.message }))
  }, [sel])
  const shown = (files.data || []).filter((f) => f.id.toLowerCase().includes(filter.toLowerCase())).slice(0, 80)
  const s = t?.profile?.style
  return (
    <div className="stack">
      <div><h1>Why does this code look the way it does?</h1>
        <p className="lede">Follow a file back through the commits, pull requests, review threads, tickets and decisions that shaped it, oldest first.</p></div>
      <div className="split">
        <div className="stack-s">
          <input type="search" placeholder="Filter files" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter files" />
          <ul className="list" style={{ maxHeight: 520, overflowY: 'auto' }}>{shown.map((f) => <li key={f.id}><button className={sel === f.id ? 'on' : ''} onClick={() => setSel(f.id)}><code>{f.id.replace(':', ' / ')}</code></button></li>)}</ul>
        </div>
        <div className="stack">
          {!sel && <p className="notice">Pick a file to see its history.</p>}
          {err && <Problem error={err} />}
          {t && (
            <>
              <div className="stack-s">
                <h2><code style={{ fontSize: 17 }}>{t.repo} / {t.path}</code></h2>
                
                {t.url && <a className="small" href={t.url} target="_blank" rel="noreferrer">Open the file</a>}
              </div>
              {!ex && <Reading>Reading the history of this file</Reading>}
              {ex?.status === 'ok' && (
                <div className="turn">
                  <Strata ids={[...(ex.headline?.cites || []), ...ex.points.flatMap((p) => p.cites)]} />
                  <div className="stack-s">
                    {ex.headline && <p className="headline"><Hl text={ex.headline.text} k={ex.headline.key} /></p>}
                    {ex.points.map((p, i) => <p key={i} style={{ maxWidth: '64ch', margin: '0 0 8px' }}><Hl text={p.text} k={p.key} /> <Tags ids={p.cites} land={i + 1} /></p>)}
                  </div>
                </div>
              )}
              {ex && ex.status !== 'ok' && <p className="notice">{ex.status === 'llm_required' || ex.status === 'error' ? `The explanation needs a language model: ${ex.note || ''} The history is below.` : 'The history is too thin to say more than what is listed below.'}</p>}
              {t.profile.comments.length > 0 && <section className="sect"><h2>Comments in the code</h2>
                <ul style={{ paddingLeft: 18, margin: 0 }}>{t.profile.comments.slice(0, 8).map((c) => <li key={c.line} className="small"><code>line {c.line}</code> {c.text}</li>)}</ul></section>}
              <details className="evidence" open={ex && ex.status !== 'ok'}><summary>The evidence: {t.events.length} items, oldest first</summary>
                {s && s.functions > 0 && <p className="small muted num" style={{ marginBottom: 14 }}>{s.functions} functions, {s.classes} classes; {s.args_annotated} of {s.args_total} arguments and {s.returns_annotated} of {s.functions} return values annotated; {s.with_docstring} with a docstring; {s.comment_lines} comment lines; {s.snake_case} of {s.functions} names in snake_case.</p>}
                <ul className="core">
                  {t.events.map((e, i) => (
                    <li key={i} style={{ '--tc': (TYPES[KIND[e.kind]] || TYPES.fact).color }}>
                      <div className="when">{e.when ? ago(e.when) : 'undated'}{e.who ? ` · ${shortName(e.who)}` : ''} · {LABEL[e.kind]} {e.ref}</div>
                      <button className="what" style={{ background: 'none', border: 0, padding: 0, textAlign: 'left', cursor: 'pointer' }} onClick={() => col.open({ id: e.id, label: e.title })}>{e.title}</button>
                      {e.kind === 'discussion' && <div className="words small" style={{ marginTop: 4 }}>{(e.body || '').slice(0, 260)}</div>}
                    </li>
                  ))}
                </ul></details>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
