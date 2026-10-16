import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Proof, Reading, Tags, ago, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const REL = { restates: 'says it again', follows: 'follows it', conflicts: 'goes against it', replaces: 'replaces it', mentions: 'mentions it' }
const VERDICT = { holds: 'Still holds', contradicted: 'Contradicted by later work', replaced: 'Replaced by a later decision', unclear: 'Unclear' }
const DOT = { holds: '', contradicted: 'contradicted', replaced: 'contradicted', unclear: 'inferred' }

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
  const proof = t ? [...(t.events || []).slice().reverse().filter((e) => e.quote).map((e) => ({ id: e.id, quote: e.quote })),
    ...(origin?.original ? [{ id: origin.id, quote: origin.original.split(/(?<=[.!?])\s/)[0].slice(0, 220) }] : [])] : []
  return (
    <div className="stack">
      <div><h1>Standards nobody wrote down, until now.</h1>
        <p className="lede">A reviewer said it once, in a pull request. Here is who, when, and whether later work kept to it.</p></div>
      {list.data?.length === 0 && <p className="notice">Nothing remembered yet. Standards appear once review comments have been read.</p>}
      <div className="split">
        <ul className="list" aria-label="Remembered standards">
          {(list.data || []).map((g) => (
            <li key={g.id}><button className={sel?.id === g.id ? 'on' : ''} onClick={() => { setSel(g); setErr(null) }}>
              <div style={{ fontWeight: 500 }}>{g.summary.split(':')[0]}</div>
              <div className="small muted">{shortName(g.source?.author)} · {ago(g.date)}</div>
            </button></li>
          ))}
        </ul>
        {sel && (
          <div className="stack">
            <div className="stack-s">
              <h2>{sel.summary.split(':')[0]}</h2>
              {t?.verdict && <div className="verdict"><span className={`dot ${DOT[t.verdict.status]}`} />{VERDICT[t.verdict.status]}</div>}
            </div>
            {busy && <Reading>Looking for every later record that touches this topic</Reading>}
            {err && <Problem error={err} />}
            {t?.status === 'llm_required' && <p className="notice err">The write-up is down; search still works. Try again shortly. {t.note}</p>}
            {t?.verdict && (
              <div className="story">
                {(t.story || []).map((st, i) => <p key={i}><Hl text={st.text} k={st.key} /> <Tags ids={st.cites} /></p>)}
                {!(t.story || []).length && <p>{t.verdict.reason}</p>}
              </div>
            )}
            {t && <Proof items={proof} />}
            {!t && !busy && <blockquote className="q-s">{(origin?.original || '').slice(0, 420)}</blockquote>}
            {t && (
              <details className="evidence">
                <summary>Show the full timeline ({t.events.length + 1})</summary>
                <ul className="core" aria-label="Timeline, newest first">
                  {(t.events || []).slice().reverse().map((e) => (
                    <li key={e.id}>
                      <div className="when">{ago(e.date)}{e.author ? ` · ${shortName(e.author)}` : ''} · <span className="rel">{REL[e.relation] || e.relation}</span></div>
                      <div className="what">{e.title}</div>
                      <button type="button" className="pcard" style={{ marginTop: 8 }} onClick={() => col.open({ id: e.id, quote: e.quote, label: e.title })}><span className="pq">{e.quote}</span></button>
                      <div className="small muted" style={{ marginTop: 6 }}>{e.note}</div>
                    </li>
                  ))}
                  <li>
                    <div className="when">{ago(origin?.date)} · {shortName(origin?.author)} · where it started</div>
                    <div className="what">{origin?.title}</div>
                    <button type="button" className="pcard" style={{ marginTop: 8 }} onClick={() => col.open({ id: origin.id, label: origin.title })}><span className="pq">{(origin?.original || '').slice(0, 320)}{(origin?.original || '').length > 320 ? '…' : ''}</span></button>
                  </li>
                </ul>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
