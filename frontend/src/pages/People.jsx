import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading, Tags, ago, copyText, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const SECTIONS = [['only_they_know', 'Mostly their history'], ['poorly_documented', 'Little or nothing written down'], ['open_work', 'Unfinished work'], ['people_to_ask', 'Who could be asked'],
  ['standards_they_set', 'Standards they set'], ['risks', 'What is lost if nothing is done'], ['first_week', 'Handover actions for the first week']]
const full = (login) => login.split('.').map((x) => x.replace(/^./, (c) => c.toUpperCase())).join(' ')

function Brief({ b }) {
  const reg = Object.fromEntries((b.citations || []).map((c) => [c.id, { label: c.label, status: c.status }]))
  const md = [`# Handover: ${b.login}`, b.summary, ...SECTIONS.flatMap(([k, l]) => b[k]?.length ? [`## ${l}`, ...b[k].map((i) => `- ${i.text}`)] : [])].join('\n')
  if (b.status === 'llm_required') return <p className="notice err">The write-up is down; search still works. Try again shortly. The computed profile below is complete without it.</p>
  if (b.status !== 'ok') return null
  return (
    <div className="stack">
      <p className="headline">{b.summary}</p>
      {SECTIONS.map(([k, l]) => b[k]?.length > 0 && (
        <section key={k}><h2>{l}</h2>
          <div className="answer" style={{ marginTop: 12 }}>{b[k].map((it, i) => <p key={i}><Hl text={it.text} k={it.key} /> <Tags ids={it.cites} registry={reg} /></p>)}</div>
        </section>
      ))}
      <div><button className="btn quiet small" onClick={() => copyText(md)}>Copy brief</button></div>
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
  const prep = async (who) => {
    setBusy(true); setErr(null)
    try { setBrief((b) => ({ ...b, [who]: null })); const r = await api.handover(who); setBrief((b) => ({ ...b, [who]: r })) } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  useEffect(() => { if (sel) { setProf(null); api.person(sel).then(setProf).catch(setErr); if (brief[sel] === undefined) prep(sel) } }, [sel]) // eslint-disable-line
  return (
    <div className="stack">
      <div><h1>If this person became unavailable tomorrow, what would be hard to replace?</h1>
        <p className="lede">Worked out from commits, pull requests, reviews and tickets. Commit history shows who changed a file, not who understands it, so treat every name as someone to ask, not as the owner.</p></div>
      <div className="split">
        <ul className="list" aria-label="People">
          {(list.data || []).map((p) => (
            <li key={p.login}><button className={sel === p.login ? 'on' : ''} onClick={() => { setSel(p.login); setErr(null) }}>
              <div style={{ fontWeight: 500 }}>{full(p.login)}{p.bot && <span className="small muted"> · bot</span>}</div>
              <div className="small muted">{p.bot ? 'Automated account' : `Last active ${ago(p.last_active)}`}</div>
            </button></li>
          ))}
        </ul>
        {prof && (
          <div className="stack">
            <div className="stack-s">
              <h2>{full(prof.login)}</h2>
              <p className="muted">{prof.commits} commits · last active {ago(prof.last_active)} · {prof.areas.filter((a) => a.share >= 0.9 && a.total >= 3).length} areas where they wrote nearly all of the history</p>
              <button className="btn quiet small" onClick={() => prep(sel)} disabled={busy}>Write the handover again</button>
            </div>
            {prof.components?.length > 0 && (
              <div><div className="small muted">Components they touched (counts of file changes, not expertise)</div>
                <table className="tbl"><tbody>{prof.components.map((c) => (
                  <tr key={c.repo}><td>{c.repo}</td><td className="num">{c.files} file{c.files === 1 ? '' : 's'}</td><td className="num muted">{c.their_touches} of {c.all_touches} changes</td></tr>))}</tbody></table></div>
            )}
            {busy && <Reading>Writing the handover from {prof.areas.length} areas, {prof.pull_requests.length} PRs and {prof.comments.length} review comments</Reading>}
            {err && <Problem error={err} />}
            {brief[sel] && <Brief b={brief[sel]} />}
            <details className="evidence"><summary>Show the evidence ({prof.areas.length} code areas, {prof.comments.length} review comments)</summary>
              <table className="tbl"><thead><tr><th>File</th><th>Their share</th><th>Others who touched it</th><th>Written down</th></tr></thead><tbody>
                {prof.areas.map((a) => (
                  <tr key={a.id}><td><button className="tag" onClick={() => col.open({ id: a.id, label: prof.evidence[a.id]?.label })}><span className="n">{a.repo}/{a.file}</span></button></td>
                    <td style={{ minWidth: 160 }}><div className="bar"><i style={{ width: `${a.share * 100}%` }} /></div><span className="small muted">{a.commits} of {a.total} commits</span></td>
                    <td className="small">{a.others.map((o) => `${shortName(o.login)} (${o.commits}${o.still_active ? ', active' : ', inactive'})`).join(', ') || <span className="muted">nobody</span>}</td>
                    <td className="small">{a.docs_mentioning ? `${a.docs_mentioning} doc${a.docs_mentioning === 1 ? '' : 's'} mention it` : <span className="muted">none found</span>}</td></tr>
                ))}
              </tbody></table>
              {prof.comments.length > 0 && <div style={{ marginTop: 20 }}>{prof.comments.slice(0, 6).map((c) => <p key={c.id} className="small" style={{ marginBottom: 8 }}><Tags ids={[c.id]} registry={prof.evidence} /> {c.text.slice(0, 160)}{c.text.length > 160 ? '…' : ''}</p>)}</div>}
            </details>
          </div>
        )}
      </div>
    </div>
  )
}
