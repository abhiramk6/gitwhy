import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Problem, Reading, Strata, Tags, ago, copyText, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const KIND = {
  past_guidance: 'A reviewer already said this', decision_violation: 'Conflicts with a decision', superseded_reference: 'Follows a replaced decision',
  ownership_risk: 'Ownership', dependency_impact: 'Downstream impact', runbook_reminder: 'Runbook', missing_override: 'Exception not recorded',
  reuse_opportunity: 'Reuse an existing component', other: 'Note',
}

function Draft({ r }) {
  const [off, setOff] = useState({})
  const col = useColumn()
  const reg = r.evidence || {}
  const ids = [...new Set(r.comments.flatMap((c) => c.evidence))]
  const md = r.comments.filter((c, i) => !off[i]).map((c) => `**${KIND[c.type] || c.type}**${c.file ? ` (${c.file})` : ''}\n${c.comment}${c.quote ? `\n> ${c.quote}` : ''}`).join('\n\n')
  return (
    <div className="stack">
      <p className="draft-banner">Draft. Nothing is posted to GitHub or anywhere else; copy what you want to keep.</p>
      {r.status === 'llm_required' && <p className="notice err">Drafting needs a language model and none is available. {r.explanation}</p>}
      {r.nothing_to_say && r.status === 'draft' && <p className="notice ok">Nothing to say. No comment was supported by the sources, so none is invented.</p>}
      <div className="turn" style={{ display: r.comments.length ? 'grid' : 'none' }}>
        <Strata ids={ids} />
        <div>
          {r.comments.map((c, i) => (
            <div key={i} className={`cm${off[i] ? ' off' : ''}`}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="typ">{KIND[c.type] || c.type}{c.file && <code style={{ marginLeft: 8 }}>{c.file}</code>}</span>
                <span className="row">
                  <span className="small muted"><span className={`mark ${c.label === 'verified' ? '' : 'inferred'}`} />{c.label}</span>
                  <button className="btn quiet small" onClick={() => setOff({ ...off, [i]: !off[i] })}>{off[i] ? 'Keep' : 'Discard'}</button>
                </span>
              </div>
              <p style={{ margin: '6px 0' }}>{c.comment}</p>
              {c.quote && <blockquote className="q-s" onClick={() => col.open({ id: c.evidence[0], quote: c.quote, label: reg[c.evidence[0]]?.label })} style={{ cursor: 'pointer' }}>{c.quote}</blockquote>}
              <div><Tags ids={c.evidence} registry={reg} quote={c.quote} land={i + 1} /></div>
            </div>
          ))}
        </div>
      </div>
      {r.comments.length > 0 && <div className="row"><button className="btn quiet small" onClick={() => copyText(md)}>Copy kept comments</button></div>}
      {r.dropped?.length > 0 && (
        <details className="small muted"><summary>{r.dropped.length} draft comment{r.dropped.length > 1 ? 's were' : ' was'} discarded by the evidence guard</summary>
          <ul>{r.dropped.map((d, i) => <li key={i}>{d.reason}: {d.comment}</li>)}</ul></details>
      )}
      {r.provenance && <p className="small muted">{r.provenance.limitations}. Model {r.provenance.model || 'n/a'}, {r.provenance.model_calls_live} live call(s), {r.provenance.replayed} replayed.</p>}
    </div>
  )
}

export default function Review() {
  const prs = useAsync(api.prs)
  const [sel, setSel] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [drafts, setDrafts] = useState({})
  useEffect(() => { if (!sel && prs.data?.length) setSel(prs.data[0]) }, [prs.data, sel])
  const draft = async () => {
    setBusy(true); setErr(null)
    try { const r = await api.reviewPr(sel.repo, sel.number); setDrafts((d) => ({ ...d, [sel.id]: r })) } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  return (
    <div className="stack">
      <div><h1>Review a pull request against what the team has said before</h1>
        <p className="lede">Pick a PR. The draft cites earlier review threads, decisions and ownership history. Pull requests are read at file level, so no comment claims anything about specific lines.</p></div>
      <div className="split">
        <ul className="list" aria-label="Pull requests">
          {(prs.data || []).map((p) => (
            <li key={p.id}><button className={sel?.id === p.id ? 'on' : ''} onClick={() => { setSel(p); setErr(null) }}>
              <div style={{ fontWeight: 600 }}>{p.title}</div>
              <div className="small muted">{p.id} · {shortName(p.author)} · {ago(p.merged_at)}{p.comments === 0 ? ' · no review thread' : ` · ${p.comments} comments`}</div>
            </button></li>
          ))}
        </ul>
        {sel && (
          <div className="stack">
            <div className="stack-s">
              <h2>{sel.title}</h2>
              <p className="small muted">{sel.id} by {shortName(sel.author)} · {ago(sel.merged_at)} · {sel.files.join(', ')}</p>
              <div className="row"><button className="btn" onClick={draft} disabled={busy}>{drafts[sel.id] ? 'Draft again' : 'Draft review'}</button>
                {sel.url && <a className="small" href={sel.url} target="_blank" rel="noreferrer">Open the PR</a>}</div>
            </div>
            {busy && <Reading>Checking this PR against decisions, earlier threads and ownership</Reading>}
            {err && <Problem error={err} />}
            {drafts[sel.id] && !busy && <Draft r={drafts[sel.id]} />}
          </div>
        )}
      </div>
    </div>
  )
}
