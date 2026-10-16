import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading, Tags, ago, copyText, shortName, useColumn } from '../ui.jsx'
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
  const md = r.comments.filter((c, i) => !off[i]).map((c) => `**${KIND[c.type] || c.type}**${c.in_pr ? ` (${c.in_pr.file}:${c.in_pr.line})` : c.file ? ` (${c.file})` : ''}\n${c.comment}${c.quote ? `\n> ${c.quote}` : ''}`).join('\n\n')
  return (
    <div className="stack-s">
      {r.status === 'llm_required' && <p className="notice err">The write-up is down; search still works. Try again shortly. {r.explanation}</p>}
      {r.nothing_to_say && r.status === 'draft' && <p className="notice">No source backs a comment on this PR, so we're not saying anything.</p>}
      {r.comments.map((c, i) => (
        <div key={i} className={`cm${off[i] ? ' off' : ''}`}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="typ">{KIND[c.type] || c.type}{c.file && !c.earlier && <> · <code>{c.file}</code></>}</span>
            <span className="row"><span className="small muted"><span className={`dot ${c.label === 'verified' ? '' : 'inferred'}`} />{c.label}</span>
              <button className="btn quiet small" onClick={() => setOff({ ...off, [i]: !off[i] })}>{off[i] ? 'Keep' : 'Discard'}</button></span>
          </div>
          {c.earlier ? (
            <div className="stack-s">
              <div>
                <div className="small muted">{c.earlier.kind === 'review' ? 'What was said' : 'The decision'} · {c.earlier.who ? shortName(c.earlier.who) : 'author not recorded'}{c.earlier.when ? ` · ${c.earlier.when}` : ''}</div>
                {c.earlier.quote && (
                  <button type="button" className="pcard" onClick={() => col.open({ id: c.earlier.id, quote: c.earlier.quote, label: reg[c.earlier.id]?.label })}>
                    <span className="pmeta">“ source</span><span className="pq">{c.earlier.quote}</span></button>)}
              </div>
              {c.trigger?.where === 'diff' || c.in_pr
                ? (() => { const t = c.trigger?.where === 'diff' ? c.trigger : c.in_pr; return <div><div className="small muted">In this PR · <code>{t.file}</code> line {t.line}</div><pre className="diffline">{t.text}</pre></div> })()
                : c.trigger
                  ? <div><div className="small muted">In this PR · {c.trigger.where === 'files' ? 'a changed file' : c.trigger.where === 'imports' ? 'an added import' : `the ${c.trigger.where}`}</div><p className="text" style={{ margin: 0 }}>“{c.trigger.text}”</p></div>
                  : <div className="small muted">In this PR · {c.file ? <><code>{c.file}</code>, file level</> : 'whole PR'}</div>}
              {c.why && <div><div className="small muted">Why they conflict</div><p className="text" style={{ margin: 0 }}>{c.why}</p></div>}
              <div><div className="small muted">Suggested review comment</div><p className="text" style={{ margin: 0 }}><Hl text={c.comment} k={c.key} /></p></div>
            </div>
          ) : (
            <>
              <p className="text"><Hl text={c.comment} k={c.key} /></p>
              {c.quote && (
                <button type="button" className="pcard" onClick={() => col.open({ id: c.evidence[0], quote: c.quote, label: reg[c.evidence[0]]?.label })}>
                  <span className="pmeta">“ source</span><span className="pq">{c.quote}</span></button>
              )}
            </>
          )}
          <div style={{ marginTop: 12 }}><Tags ids={c.evidence} registry={reg} quote={c.quote} /></div>
        </div>
      ))}
      {r.comments.length > 0 && <div className="row"><button className="btn quiet small" onClick={() => copyText(md)}>Copy kept comments</button></div>}
      <details className="disc small muted"><summary>Draft only · discarded comments · how this was made</summary>
        <p>Draft. Nothing is posted to GitHub or anywhere else.</p>
        {r.dropped?.length > 0 && <ul>{r.dropped.map((d, i) => <li key={i}>{d.reason}: {d.comment}</li>)}</ul>}
        {r.provenance && <p>{r.provenance.limitations}. Model {r.provenance.model || 'n/a'}, {r.provenance.model_calls_live} live call(s), {r.provenance.replayed} replayed.</p>}
      </details>
    </div>
  )
}

export default function Review() {
  const prs = useAsync(api.prs)
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [drafts, setDrafts] = useState({})
  useEffect(() => { if (!sel && prs.data?.length) setSel(prs.data[0]) }, [prs.data, sel])
  const shown = useMemo(() => (prs.data || []).filter((p) => `${p.id} ${p.title}`.toLowerCase().includes(filter.toLowerCase())).slice(0, 40), [prs.data, filter])
  const draft = async () => {
    setBusy(true); setErr(null)
    try { const r = await api.reviewPr(sel.repo, sel.number); setDrafts((d) => ({ ...d, [sel.id]: r })) } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  useEffect(() => { if (sel && !drafts[sel.id] && !busy) draft() }, [sel?.id]) // eslint-disable-line
  return (
    <div className="stack">
      <div><h1>Check a pull request against what reviewers already said.</h1>
        <p className="lede">Comments cite earlier review threads, decisions and ownership. Nothing is posted anywhere.</p></div>
      <div>
        <div className="picker">
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600 }}>{sel?.title || 'Choose a pull request'}</div>
            {sel && <div className="small muted">{sel.id} · {shortName(sel.author)} · {ago(sel.merged_at)} · {sel.files.join(', ')}</div>}
          </div>
          <button className="btn quiet small" onClick={() => setOpen((o) => !o)}>{open ? 'Close' : 'Change'}</button>
        </div>
        {open && (
          <div className="pop">
            <input type="search" placeholder="Search pull requests" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search pull requests" />
            <ul className="list" style={{ marginTop: 8 }}>{shown.map((p) => (
              <li key={p.id}><button onClick={() => { setSel(p); setOpen(false); setErr(null) }}><div style={{ fontWeight: 500 }}>{p.title}</div>
                <div className="small muted">{p.id} · {shortName(p.author)} · {ago(p.merged_at)}{p.comments ? ` · ${p.comments} comments` : ''}</div></button></li>))}</ul>
          </div>
        )}
      </div>
      {busy && <Reading>Checking this PR against decisions, earlier threads and ownership</Reading>}
      {err && <Problem error={err} />}
      {sel && drafts[sel.id] && !busy && <Draft r={drafts[sel.id]} />}
    </div>
  )
}
