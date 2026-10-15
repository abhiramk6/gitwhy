import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Async, Badge, Card, fmt, useAsync } from '../components.jsx'

const EXAMPLES = {
  northwind: 'Add support for partial refunds on captured payments (PAY-142)',
  'oss-pallets': 'Let Flask session cookies survive a secret key rotation without logging users out',
}
const DEFAULT_EXAMPLE = EXAMPLES.northwind

function Evidence({ ids, registry, onPick }) {
  return (
    <div className="chips">
      {(ids || []).map((id) => (
        <button key={id} className="signal btn" onClick={() => onPick(registry[id] || { id, label: 'missing evidence' })}>{registry[id]?.kind || 'evidence'}</button>
      ))}
    </div>
  )
}

function Plan({ plan, reload }) {
  const [picked, setPicked] = useState(null)
  const [msg, setMsg] = useState(null)
  const reg = plan.evidence || {}
  if (plan.status === 'insufficient_evidence') {
    return <Card title="Not enough evidence">{plan.open_questions.map((q, i) => <p key={i}>{q.summary || q}</p>)}</Card>
  }
  if (plan.status === 'llm_required') {
    return (
      <Card title="LLM layer required">
        {plan.open_questions.map((q, i) => <p key={i}>{q.summary || q}</p>)}
        <p className="muted">Configure PROVIDER=gemini (GEMINI_API_KEY) or PROVIDER=vertex. Rule-based guessing is intentionally not offered.</p>
      </Card>
    )
  }
  const act = async (status) => {
    try { await api.setPlanStatus(plan.id, status); setMsg(`Plan ${status}.`); reload() } catch (e) { setMsg(e.message) }
  }
  return (
    <div className="grid-graph">
      <div>
        <Card title="Plan" right={<span className="muted">#{plan.id} · {plan.plan_status} · {plan.provider}</span>}>
          <p>{plan.request}</p>
          <ul>{plan.assumptions.map((a, i) => <li key={i} className="muted">{a}</li>)}</ul>
          {plan.search_mode && <div className="muted">search: {plan.search_mode}</div>}
          {(plan.dropped_claims || []).length > 0 && (
            <details><summary className="muted">{plan.dropped_claims.length} model claim(s) discarded by the evidence guard</summary>
              <ul>{plan.dropped_claims.map((d, i) => <li key={i} className="muted">{d}</li>)}</ul></details>
          )}
          <div className="row">
            <button onClick={() => act('approved')} disabled={plan.plan_status === 'approved'}>Approve plan</button>
            <button className="ghost" onClick={() => act('rejected')}>Reject</button>
            {msg && <span className="muted">{msg}</span>}
          </div>
          {plan.unsupported_claims?.length > 0 && <div className="state error">Unsupported claims: {plan.unsupported_claims.join('; ')}</div>}
        </Card>
        <Card title="Affected components">
          {plan.affected_components.map((c) => (
            <div key={c.service + c.role} className="alert"><Badge kind={c.label} />
              <div><b>{c.service}</b> <span className="muted">· {c.role}{c.needs_change ? ` · change needed: ${c.needs_change}` : ''}</span><div className="muted">{c.reason}</div>
                <Evidence ids={c.evidence} registry={reg} onPick={setPicked} /></div></div>
          ))}
        </Card>
        <Card title="Governing decisions">
          {plan.decisions.length === 0 && <div className="state">No applicable decisions found.</div>}
          {plan.decisions.map((d) => (
            <div key={d.adr} className="alert"><Badge kind={d.label} /><div><b>{d.adr}</b> — {d.summary}{d.guidance ? <div className="muted">{d.guidance}</div> : null}
              <Evidence ids={d.evidence} registry={reg} onPick={setPicked} /></div></div>
          ))}
        </Card>
        <Card title="Risks and reuse">
          {[...plan.risks.map((r) => ({ ...r, kind: r.type })), ...plan.reuse_candidates.map((r) => ({ ...r, kind: 'reuse' }))].map((r, i) => (
            <div key={i} className="alert"><Badge kind={r.label} /><div><span className="muted">{r.kind}</span> — {r.summary}
              <Evidence ids={r.evidence} registry={reg} onPick={setPicked} /></div></div>
          ))}
          {plan.risks.length + plan.reuse_candidates.length === 0 && <div className="state">No risks or reuse candidates found.</div>}
        </Card>
        <Card title="Implementation tasks">
          <ol className="tasks">
            {plan.tasks.map((t) => (
              <li key={t.id}><Badge kind="proposed" /> <b>{t.id}</b> {t.title}
                <div className="muted">{t.service ? `${t.service} · ` : ''}{t.depends_on.length ? `after ${t.depends_on.join(', ')}` : 'no dependencies'} — {t.rationale}</div>
                <Evidence ids={t.evidence} registry={reg} onPick={setPicked} /></li>
            ))}
          </ol>
        </Card>
        <Card title="Tests and open questions">
          {plan.tests.map((t, i) => <div key={i} className="alert"><Badge kind="proposed" /><div>{t.check}</div></div>)}
          {plan.open_questions.map((q, i) => (
            <div key={i} className="alert"><Badge kind={q.label} /><div>{q.summary}<Evidence ids={q.evidence} registry={reg} onPick={setPicked} /></div></div>
          ))}
        </Card>
      </div>
      <Card title="Evidence inspector">
        {!picked && <div className="state">Click an evidence chip to see where a claim comes from.</div>}
        {picked && (
          <dl>
            <dt>Claim source</dt><dd>{picked.label}</dd>
            <dt>Kind</dt><dd>{picked.kind}</dd>
            <dt>Evidence type</dt><dd>{picked.evidence_type} <Badge kind={['structural', 'explicit'].includes(picked.evidence_type) && picked.status === 'active' ? 'verified' : 'inferred'} /></dd>
            <dt>Status</dt><dd>{picked.status}</dd>
            <dt>Source</dt><dd>{picked.source ? (String(picked.source).startsWith('http') ? <a href={picked.source} target="_blank" rel="noreferrer">{picked.source}</a> : picked.source) : 'derived from retrieved evidence'}</dd>
            <dt>Id</dt><dd><code>{picked.id}</code></dd>
          </dl>
        )}
      </Card>
    </div>
  )
}

export default function Planner() {
  const [example, setExample] = useState(DEFAULT_EXAMPLE)
  const [text, setText] = useState(DEFAULT_EXAMPLE)
  useEffect(() => {
    api.overview().then((o) => {
      const ex = EXAMPLES[o.organization.slug]
      if (ex) { setExample(ex); setText((t) => (t === DEFAULT_EXAMPLE ? ex : t)) }
    }).catch(() => {})
  }, [])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [plan, setPlan] = useState(null)
  const past = useAsync(api.plans)

  const run = async () => {
    setBusy(true); setErr(null)
    try { setPlan(await api.createPlan(text)); past.reload() } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  const open = async (id) => { try { setPlan(await api.plan(id)) } catch (e) { setErr(e) } }
  return (
    <div className="page">
      <h1>Feature planner</h1>
      <Card title="Feature request">
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label="Feature request" />
        <div className="row">
          <button onClick={run} disabled={busy || text.trim().length < 8}>{busy ? 'Planning…' : 'Generate plan'}</button>
          <button className="ghost" onClick={() => setText(example)}>Use example</button>
        </div>
        {err && <div className="state error" role="alert">
          {err.status === 401 ? 'Writes need the demo token (set it in the sidebar).' : err.message}</div>}
      </Card>
      <div className="past">
        <span className="muted">Previous plans:</span>
        {past.data && past.data.length === 0 && <span className="muted"> none yet</span>}
        {past.data && past.data.slice(0, 5).map((p) => (
          <button key={p.id} className="link" onClick={() => open(p.id)}>#{p.id} {p.status} · {fmt(p.created_at)}</button>
        ))}
      </div>
      {plan && <Plan plan={plan} reload={() => open(plan.id)} />}
      {!plan && !busy && <div className="state">Describe a feature to see affected services, governing decisions, risks and a task plan, each linked to evidence.</div>}
    </div>
  )
}
