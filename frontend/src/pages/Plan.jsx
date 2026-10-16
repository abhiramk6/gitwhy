import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Problem, Reading, Tags, copyText } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const EXAMPLES = {
  northwind: 'Add support for partial refunds on captured payments (PAY-142)',
  'oss-pallets': 'Let Flask session cookies survive a secret key rotation without logging users out',
}

function Line({ label, children, ids, reg }) {
  return <p style={{ margin: '0 0 12px', maxWidth: '36em', fontSize: 16 }}>{label && <span className={`dot ${label === 'inferred' ? 'inferred' : ''}`} title={label} />}{children} <Tags ids={ids} registry={reg} /></p>
}

function PlanView({ plan }) {
  const reg = plan.evidence || {}
  if (plan.status === 'insufficient_evidence') return <p className="notice">No source backs a plan for this, so we're not making one up. {plan.open_questions.map((q) => q.summary || q).join(' ')}</p>
  if (plan.status === 'llm_required') return <p className="notice err">The write-up is down; search still works. Try again shortly.</p>
  const md = [`# Plan: ${plan.request}`, '## Tasks', ...plan.tasks.map((t) => `- ${t.id} ${t.title}${t.service ? ` (${t.service})` : ''}`), '## Done when', ...(plan.acceptance_criteria || []).map((a) => `- ${a.task}: ${a.criterion}`), '## Tests', ...plan.tests.map((t) => `- ${t.check}`)].join('\n')
  return (
    <div className="stack">
      {(plan.dropped_claims || []).length > 0 && <details className="disc small muted"><summary>{plan.dropped_claims.length} claim(s) left out: no source backs them up</summary><ul>{plan.dropped_claims.map((d, i) => <li key={i}>{d}</li>)}</ul></details>}
      <section className="sect"><h2>Affected services</h2>
        {plan.affected_components.map((c) => <Line key={c.service + c.role} label={c.label} ids={c.evidence} reg={reg}><b style={{ fontWeight: 600 }}>{c.service}</b> <span className="muted">{c.role}{c.needs_change ? `, change needed: ${c.needs_change}` : ''}</span>. {c.reason}</Line>)}</section>
      <section className="sect"><h2>Decisions that apply</h2>
        {plan.decisions.length === 0 && <p className="muted">None found.</p>}
        {plan.decisions.map((d) => <Line key={d.adr} label={d.label} ids={d.evidence} reg={reg}><b style={{ fontWeight: 600 }}>{d.adr}</b>. {d.summary}</Line>)}</section>
      <section className="sect"><h2>Risks and reuse</h2>
        {[...plan.risks.map((r) => ({ ...r, kind: r.type })), ...plan.reuse_candidates.map((r) => ({ ...r, kind: 'reuse' }))].map((r, i) => <Line key={i} label={r.label} ids={r.evidence} reg={reg}><span className="muted">{String(r.kind).replace(/_/g, ' ')}.</span> {r.summary}</Line>)}
        {plan.risks.length + plan.reuse_candidates.length === 0 && <p className="muted">None found.</p>}</section>
      <section className="sect"><h2>Do this, in order</h2>
        <ol className="tasks">{plan.tasks.map((t) => <li key={t.id}><div><div className="tt">{t.title}</div>
          <div className="small muted">{t.service ? `${t.service}. ` : ''}{t.depends_on.length ? `After ${t.depends_on.join(', ')}. ` : ''}{t.rationale} <Tags ids={t.evidence} registry={reg} /></div>
          {(plan.acceptance_criteria || []).filter((a) => a.task === t.id).map((a, i) => <div key={i} className="small" style={{ marginTop: 6 }}><span className="muted">Done when</span> {a.criterion} <Tags ids={a.evidence} registry={reg} /></div>)}</div></li>)}</ol></section>
      <details className="evidence"><summary>Tests and open questions</summary>
        {plan.tests.map((t, i) => <p key={i} style={{ margin: '0 0 8px' }}>{t.check}</p>)}
        {plan.open_questions.map((q, i) => <Line key={i} label={q.label} ids={q.evidence} reg={reg}>{q.summary}</Line>)}</details>
      <div className="row"><button className="btn quiet small" onClick={() => copyText(md)}>Copy as markdown</button>
        <span className="small muted">Saved as plan {plan.id}. Proposed tasks are suggestions, not facts.</span></div>
    </div>
  )
}

export default function Plan() {
  const [org, setOrg] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [plan, setPlan] = useState(null)
  const past = useAsync(api.plans)
  useEffect(() => { api.overview().then((o) => { setOrg(o.organization); setText((t) => t || EXAMPLES[o.organization.slug] || '') }).catch(() => {}) }, [])
  const run = async () => { setBusy(true); setErr(null); try { setPlan(await api.createPlan(text)); past.reload() } catch (e) { setErr(e) } finally { setBusy(false) } }
  return (
    <div className="stack">
      <div><h1>Plan a feature before you start it.</h1>
        <p className="lede">The services it touches (including ones you did not name), the decisions that apply, what can be reused, and an ordered task list, each with its source.</p></div>
      <div className="stack-s">
        <label className="sr" htmlFor="req">Feature request</label>
        <textarea id="req" className="plain" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row"><button className="btn" onClick={run} disabled={busy || text.trim().length < 8}>{busy ? 'Planning…' : 'Plan it'}</button>
          {org && EXAMPLES[org.slug] && <button className="btn quiet" onClick={() => setText(EXAMPLES[org.slug])}>Use the example</button>}</div>
      </div>
      {busy && <Reading>Reading the affected services, decisions and history</Reading>}
      {err && <Problem error={err} />}
      {past.data?.length > 0 && !plan && <p className="small muted">Earlier plans: {past.data.slice(0, 5).map((p) => <button key={p.id} className="btn quiet small" style={{ marginLeft: 6 }} onClick={() => api.plan(p.id).then(setPlan)}>{p.id}</button>)}</p>}
      {plan && <PlanView plan={plan} />}
    </div>
  )
}
