import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Problem, Reading, Strata, Tags, copyText } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const EXAMPLES = {
  northwind: 'Add support for partial refunds on captured payments (PAY-142)',
  'oss-pallets': 'Let Flask session cookies survive a secret key rotation without logging users out',
}

function Line({ label, children, ids, reg, land }) {
  return <p style={{ margin: '0 0 10px', maxWidth: '68ch' }}>{label && <span className="mark" style={label === 'inferred' ? { background: 'transparent', border: '2px solid var(--inferred)' } : undefined} title={label} />}{children} <Tags ids={ids} registry={reg} land={land} /></p>
}

function PlanView({ plan }) {
  const reg = plan.evidence || {}
  const ids = Object.keys(reg)
  if (plan.status === 'insufficient_evidence') return <p className="notice">There is not enough evidence to plan this. {plan.open_questions.map((q) => q.summary || q).join(' ')}</p>
  if (plan.status === 'llm_required') return <p className="notice err">Planning needs a language model and none is available. Rule-based guessing is intentionally not offered.</p>
  const md = [`# Plan: ${plan.request}`, '## Tasks', ...plan.tasks.map((t) => `- ${t.id} ${t.title}${t.service ? ` (${t.service})` : ''}`), '## Tests', ...plan.tests.map((t) => `- ${t.check}`)].join('\n')
  return (
    <div className="turn">
      <Strata ids={ids} />
      <div className="stack">
        {(plan.dropped_claims || []).length > 0 && <details className="small muted"><summary>{plan.dropped_claims.length} model claim(s) discarded by the evidence guard</summary><ul>{plan.dropped_claims.map((d, i) => <li key={i}>{d}</li>)}</ul></details>}
        <section className="sect"><h2>Affected services</h2>
          {plan.affected_components.map((c, i) => <Line key={c.service + c.role} label={c.label} ids={c.evidence} reg={reg} land={i + 1}><b>{c.service}</b> <span className="muted">({c.role}{c.needs_change ? `, change needed: ${c.needs_change}` : ''})</span>. {c.reason}</Line>)}</section>
        <section className="sect"><h2>Decisions that apply</h2>
          {plan.decisions.length === 0 && <p className="muted">No applicable decisions found.</p>}
          {plan.decisions.map((d, i) => <Line key={d.adr} label={d.label} ids={d.evidence} reg={reg} land={i + 1}><b>{d.adr}</b>. {d.summary}{d.guidance ? ` ${d.guidance}` : ''}</Line>)}</section>
        <section className="sect"><h2>Risks and reuse</h2>
          {[...plan.risks.map((r) => ({ ...r, kind: r.type })), ...plan.reuse_candidates.map((r) => ({ ...r, kind: 'reuse' }))].map((r, i) => <Line key={i} label={r.label} ids={r.evidence} reg={reg} land={i + 1}><span className="muted">{String(r.kind).replace(/_/g, ' ')}.</span> {r.summary}</Line>)}
          {plan.risks.length + plan.reuse_candidates.length === 0 && <p className="muted">No risks or reuse candidates found.</p>}</section>
        <section className="sect"><h2>Tasks, in order</h2>
          <ol style={{ paddingLeft: 20, margin: 0 }}>{plan.tasks.map((t) => <li key={t.id} style={{ marginBottom: 10 }}><b>{t.title}</b>
            <div className="small muted">{t.service ? `${t.service}. ` : ''}{t.depends_on.length ? `After ${t.depends_on.join(', ')}. ` : ''}{t.rationale} <Tags ids={t.evidence} registry={reg} /></div></li>)}</ol></section>
        <section className="sect"><h2>Tests and open questions</h2>
          {plan.tests.map((t, i) => <p key={i} style={{ margin: '0 0 6px' }}>{t.check}</p>)}
          {plan.open_questions.map((q, i) => <Line key={i} label={q.label} ids={q.evidence} reg={reg}>{q.summary}</Line>)}</section>
        <div className="row"><button className="btn quiet small" onClick={() => copyText(md)}>Copy as markdown</button>
          <span className="small muted">Plan #{plan.id}, saved. Proposed tasks are suggestions, not facts.</span></div>
      </div>
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
      <div><h1>Plan a feature before you start it</h1>
        <p className="lede">Describe the change. You get the services it touches (including ones you did not name), the decisions that apply, risks, what can be reused, and an ordered task list. Each line shows its source.</p></div>
      <div className="stack-s">
        <label className="sr" htmlFor="req">Feature request</label>
        <textarea id="req" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row"><button className="btn" onClick={run} disabled={busy || text.trim().length < 8}>{busy ? 'Planning…' : 'Plan it'}</button>
          {org && EXAMPLES[org.slug] && <button className="btn quiet" onClick={() => setText(EXAMPLES[org.slug])}>Use the example</button>}</div>
      </div>
      {busy && <Reading>Reading the affected services, decisions and history</Reading>}
      {err && <Problem error={err} />}
      {past.data?.length > 0 && !plan && <p className="small muted">Earlier plans: {past.data.slice(0, 5).map((p) => <button key={p.id} className="btn quiet small" style={{ marginLeft: 6 }} onClick={() => api.plan(p.id).then(setPlan)}>#{p.id}</button>)}</p>}
      {plan && <PlanView plan={plan} />}
    </div>
  )
}
