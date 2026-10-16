import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Proof, Reading, TYPES, Tags, ago, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const REL = { restates: 'says it again', follows: 'follows it', conflicts: 'goes against it', replaces: 'replaces it', mentions: 'mentions it' }
const VERDICT = { holds: 'Still holds', contradicted: 'Contradicted by later work', replaced: 'Replaced by a later decision', unclear: 'Unclear' }

export default function Memory({ q }) {
  const list = useAsync(api.guidance)
  const col = useColumn()
  const [sel, setSel] = useState(null)
  const [tl, setTl] = useState({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  useEffect(() => { if (list.data?.length && !sel) setSel(list.data.find((g) => String(g.id) === q.get('id')) || list.data[0]) }, [list.data]) // eslint-disable-line
  const run = async () => {
    setBusy(true); setErr(null)
    try { const r = await api.timeline(sel.id); setTl((t) => ({ ...t, [sel.id]: r })) } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  useEffect(() => { if (sel && !tl[sel.id]) run() }, [sel?.id]) // eslint-disable-line
  const t = sel && tl[sel.id]
  const origin = sel?.source
  return (
    <div className="stack">
      <div><h1>Standards the team set in review threads</h1>
        <p className="lede">Nobody wrote these into a decision record. A reviewer said them once, in a pull request. Here they are, with who, when, and whether later work kept to them.</p></div>
      {list.data?.length === 0 && <p className="notice">No reviewer guidance has been remembered yet. It appears after the graph is built over review comments with a model.</p>}
      <div className="split">
        <ul className="list" aria-label="Remembered standards">
          {(list.data || []).map((g) => (
            <li key={g.id}><button className={sel?.id === g.id ? 'on' : ''} onClick={() => { setSel(g); setErr(null) }}>
              <div style={{ fontWeight: 600 }}>{g.summary.split(':')[0]}</div>
              <div className="small muted">{shortName(g.source?.author)} · {ago(g.date)} · {g.source?.pr}</div>
            </button></li>
          ))}
        </ul>
        {sel && (
          <div className="stack">
            <div className="stack-s">
              <h2>{sel.summary.split(':')[0]}</h2>
              <p>{sel.summary.split(':').slice(1).join(':').split(' (said by')[0].trim()}</p>
              <div className="row"><button className="btn" onClick={run} disabled={busy}>{t ? 'Check again' : 'Checking…'}</button>
                <span className="small muted">Scope: {sel.scope === 'org' ? 'whole organization' : origin?.repo}</span></div>
            </div>
            {busy && <Reading>Looking for every later record that touches this topic</Reading>}
            {err && <Problem error={err} />}
            {t?.status === 'llm_required' && <p className="notice err">Placing later records against this standard needs a language model. {t.note}</p>}
            {t?.verdict && (
              <div className="story stack-s">
                <span className={`pill ${t.verdict.status}`}>{VERDICT[t.verdict.status]}</span>
                {(t.story || []).map((st, i) => <p key={i}><Hl text={st.text} k={st.key} /> <Tags ids={st.cites} land={i + 1} /></p>)}
                {!(t.story || []).length && <p>{t.verdict.reason}</p>}
              </div>
            )}
            {t && <Proof items={[...(t.events || []).slice().reverse().filter((e) => e.quote).map((e) => ({ id: e.id, quote: e.quote })),
              ...(origin?.original ? [{ id: origin.id, quote: origin.original.split(/(?<=[.!?])\s/)[0].slice(0, 220) }] : [])]} />}
            {t && (
              <details className="evidence" open={!t.story?.length}>
                <summary>The evidence: {t.events.length} later record{t.events.length === 1 ? '' : 's'} and where it started</summary>
                <ul className="core" aria-label="Timeline, newest first">
                  {(t.events || []).slice().reverse().map((e) => (
                    <li key={e.id} style={{ '--tc': (TYPES[e.type] || TYPES.fact).color }}>
                      <div className="when">{ago(e.date)}{e.author ? ` · ${shortName(e.author)}` : ''}</div>
                      <div className="rel">{REL[e.relation] || e.relation}</div>
                      <div className="what">{e.title}</div>
                      <blockquote className="q-s" style={{ cursor: 'pointer', borderColor: (TYPES[e.type] || TYPES.fact).color }} onClick={() => col.open({ id: e.id, quote: e.quote, label: e.title })}>{e.quote}</blockquote>
                      <div className="small muted">{e.note}</div>
                    </li>
                  ))}
                  <li className="cur" style={{ '--tc': 'var(--t-thread)' }}>
                    <div className="when">{ago(origin?.date)} · {shortName(origin?.author)} · where it started</div>
                    <div className="what">{origin?.title}</div>
                    <blockquote className="q-s" style={{ cursor: 'pointer' }} onClick={() => col.open({ id: origin.id, label: origin.title })}>{(origin?.original || '').slice(0, 420)}{(origin?.original || '').length > 420 ? '…' : ''}</blockquote>
                  </li>
                </ul>
              </details>
            )}
            {!t && !busy && (
              <blockquote className="q-s" style={{ cursor: 'pointer' }} onClick={() => col.open({ id: origin.id, label: origin.title })}>{(origin?.original || '').slice(0, 420)}{(origin?.original || '').length > 420 ? '…' : ''}</blockquote>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
