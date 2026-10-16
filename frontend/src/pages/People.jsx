import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading, Strata, Tags, ago, copyText, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const SECTIONS = [['only_they_know', 'Only they know'], ['standards_they_set', 'Standards they set'], ['open_work', 'Open work'],
  ['people_to_ask', 'People to ask'], ['risks', 'What gets lost if nothing is done'], ['first_week', 'First week for the successor']]

function Brief({ b }) {
  const reg = Object.fromEntries((b.citations || []).map((c) => [c.id, { label: c.label, status: c.status }]))
  const ids = (b.citations || []).map((c) => c.id)
  const md = [`# Handover: ${b.login}`, b.summary, ...SECTIONS.flatMap(([k, l]) => b[k]?.length ? [`## ${l}`, ...b[k].map((i) => `- ${i.text}`)] : [])].join('\n')
  return (
    <div className="stack">
      {b.status === 'llm_required' && <p className="notice err">The brief needs a language model and none is available. The computed profile above is complete without one. {b.note}</p>}
      {b.status === 'ok' && (
        <div className="turn">
          <Strata ids={ids} />
          <div className="stack">
            <p className="headline" style={{ fontSize: 22 }}>{b.summary}</p>
            {SECTIONS.map(([k, l]) => b[k]?.length > 0 && (
              <section key={k} className="sect"><h2>{l}</h2>
                {b[k].map((it, i) => <p key={i} style={{ margin: '0 0 12px', maxWidth: '66ch', fontSize: 16 }}><Hl text={it.text} k={it.key} /> <Tags ids={it.cites} registry={reg} land={i + 1} /></p>)}
              </section>
            ))}
            <div><button className="btn quiet small" onClick={() => copyText(md)}>Copy brief</button></div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function People() {
  const list = useAsync(api.people)
  const [sel, setSel] = useState(null)
  const [prof, setProf] = useState(null)
  const [brief, setBrief] = useState({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const col = useColumn()
  useEffect(() => { if (list.data?.length && !sel) setSel(list.data[0].login) }, [list.data, sel])
  useEffect(() => { if (sel) { setProf(null); api.person(sel).then(setProf).catch(setErr); if (brief[sel] === undefined) prep(sel) } }, [sel]) // eslint-disable-line
  const prep = async (who = sel) => {
    setBusy(true); setErr(null)
    try { setBrief((b) => ({ ...b, [who]: null })); const r = await api.handover(who); setBrief((b) => ({ ...b, [who]: r })) } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  return (
    <div className="stack">
      <div><h1>Who knows what, and what leaves with them</h1>
        <p className="lede">Computed from commits, pull requests, reviews and tickets. Pick someone who is leaving to prepare a handover for their successor.</p></div>
      <div className="split">
        <ul className="list" aria-label="People">
          {(list.data || []).map((p) => (
            <li key={p.login}><button className={sel === p.login ? 'on' : ''} onClick={() => { setSel(p.login); setErr(null) }}>
              <div style={{ fontWeight: 600 }}>{shortName(p.login)} {p.login.split('.')[1] ? p.login.split('.')[1].replace(/^./, (c) => c.toUpperCase()) : ''}</div>
              <div className="small muted num">{p.commits} commits · {p.prs} PRs · {p.comments} review comments · last active {ago(p.last_active)}</div>
            </button></li>
          ))}
        </ul>
        {prof && (
          <div className="stack">
            <div className="stack-s">
              <h2>{shortName(prof.login)} {prof.login.split('.')[1]?.replace(/^./, (c) => c.toUpperCase())}</h2>
              <p className="small muted">Last active {ago(prof.last_active)}. {prof.areas.filter((a) => a.share >= 0.9 && a.total >= 3).length} code areas where they wrote 90% or more of the history.</p>
              <div className="row"><button className="btn quiet small" onClick={() => prep()} disabled={busy}>Rewrite the brief</button></div>
            </div>
            {busy && <Reading>Writing the brief from {prof.areas.length} areas, {prof.pull_requests.length} PRs and {prof.comments.length} review comments</Reading>}
            {err && <Problem error={err} />}
            {brief[sel] && <Brief b={brief[sel]} />}
            <details className="evidence"><summary>The evidence: {prof.areas.length} code areas, {prof.comments.length} review comments</summary>
              <table className="tbl"><thead><tr><th>File</th><th>Their share</th><th>Others who touched it</th></tr></thead><tbody>
                {prof.areas.map((a) => (
                  <tr key={a.id}><td><button className="tag" style={{ '--tc': 'var(--t-code)' }} onClick={() => col.open({ id: a.id, label: prof.evidence[a.id]?.label })}><span className="g">‹›</span><span className="n">{a.repo}/{a.file}</span></button></td>
                    <td className="num" style={{ minWidth: 150 }}><div className="bar"><i style={{ width: `${a.share * 100}%` }} /></div><span className="small muted">{a.commits} of {a.total} commits</span></td>
                    <td className="small">{a.others.map((o) => `${shortName(o.login)} (${o.commits})`).join(', ') || <span className="muted">nobody</span>}</td></tr>
                ))}
              </tbody></table>
            <div style={{ height: 18 }} />
            {prof.facts.length > 0 && <section className="sect"><h2>Remembered about them</h2>
              {prof.facts.map((f) => <p key={f.id} style={{ marginBottom: 8 }}>{f.summary} <Tags ids={[f.id]} registry={prof.evidence} /></p>)}</section>}
            {prof.comments.length > 0 && <section className="sect"><h2>Review comments they wrote</h2>
              {prof.comments.slice(0, 6).map((c) => <p key={c.id} className="small" style={{ marginBottom: 8 }}><Tags ids={[c.id]} registry={prof.evidence} /> {c.text.slice(0, 160)}{c.text.length > 160 ? '…' : ''}</p>)}</section>}
            </details>
          </div>
        )}
      </div>
    </div>
  )
}
