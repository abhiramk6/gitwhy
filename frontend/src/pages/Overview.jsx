import { useState } from 'react'
import { api } from '../api.js'
import { Async, Badge, Card, Chip, fmt, useAsync } from '../components.jsx'

const ALERT_TITLES = {
  ownership: 'Ownership', risk: 'Risk', override: 'Convention overrides', conflict: 'Conflicting conventions', reuse: 'Reuse candidates',
}

function Search() {
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const go = async (e) => {
    e.preventDefault()
    if (q.trim().length < 2) return
    setBusy(true); setErr(null)
    try { setRes(await api.search(q.trim())) } catch (x) { setErr(x) } finally { setBusy(false) }
  }
  return (
    <Card title="Search organizational context">
      <form className="row" onSubmit={go}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ticket key, ADR, service, or a question…" aria-label="Search" />
        <button disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
      </form>
      {err && <div className="state error" role="alert">{err.message}</div>}
      {res && res.length === 0 && <div className="state">No relevant evidence found. Try a ticket key or service name.</div>}
      {res && res.map((h) => (
        <article key={h.key.join(':')} className="hit">
          <div className="hit-title">{h.title} <span className="muted">· {h.source_type} {h.source_id}{h.repo ? ` · ${h.repo}` : ''}</span></div>
          <p>{h.snippet}</p>
          <div className="chips">
            {Object.entries(h.signals).map(([s, r]) => <span key={s} className="signal">{s} #{r}</span>)}
            {h.status && <span className="signal">{h.status}</span>}
          </div>
        </article>
      ))}
    </Card>
  )
}

export default function Overview() {
  const st = useAsync(api.overview)
  const state = { ...st }
  return (
    <div className="page">
      <h1>Organization overview</h1>
      <Async state={state} empty={null}>
        {(o) => {
          const sum = (m) => Object.values(m).reduce((a, b) => a + b, 0)
          const grouped = o.alerts.reduce((m, a) => ({ ...m, [a.fact_type]: [...(m[a.fact_type] || []), a] }), {})
          return (
            <>
              <p className="muted">{o.organization.name}{o.organization.is_synthetic && ' · synthetic demo organization'}</p>
              <div className="tiles">
                <div className="tile"><b>{o.repositories.length}</b><span>repositories</span></div>
                <div className="tile"><b>{sum(o.counts.source_records)}</b><span>source records</span></div>
                <div className="tile"><b>{sum(o.counts.entities)}</b><span>graph entities</span></div>
                <div className="tile"><b>{Object.entries(o.counts.facts).filter(([k]) => k.endsWith(':active')).reduce((a, [, n]) => a + n, 0)}</b><span>active facts</span></div>
                <div className="tile"><b>{Object.entries(o.counts.facts).filter(([k]) => k.endsWith(':candidate')).reduce((a, [, n]) => a + n, 0)}</b><span>candidates to review</span></div>
              </div>
              <Search />
              <div className="grid2">
                <Card title="Repositories">
                  <table>
                    <thead><tr><th>Name</th><th>Commits</th><th>PRs</th></tr></thead>
                    <tbody>{o.repositories.map((r) => <tr key={r.name}><td>{r.name}</td><td>{r.commits}</td><td>{r.prs}</td></tr>)}</tbody>
                  </table>
                </Card>
                <Card title="Ingestion health">
                  {o.ingestion.length === 0 ? <div className="state">No ingestion runs yet.</div> : (
                    <table>
                      <thead><tr><th>Source</th><th>Mode</th><th>Status</th><th>New</th><th>Changed</th><th>Started</th></tr></thead>
                      <tbody>{o.ingestion.map((r) => (
                        <tr key={r.id}><td>{r.source}</td><td>{r.mode}</td>
                          <td><span className={`dot ${r.status}`} />{r.status}</td>
                          <td>{r.records_new}</td><td>{r.records_changed}</td><td>{fmt(r.started_at)}</td></tr>
                      ))}</tbody>
                    </table>
                  )}
                </Card>
              </div>
              <h2>Alerts</h2>
              {o.alerts.length === 0 && <div className="state">No active alerts.</div>}
              <div className="grid2">
                {Object.entries(grouped).map(([type, items]) => (
                  <Card key={type} title={ALERT_TITLES[type] || type}>
                    {items.map((a) => (
                      <div key={a.id} className="alert">
                        <Badge kind={a.label} />
                        <div>
                          <div>{a.summary}</div>
                          <div className="muted">{a.repo ? `${a.repo} · ` : ''}{a.evidence_type} · {a.status}
                            {a.source_url && <> · <a href={a.source_url} target="_blank" rel="noreferrer">source</a></>}</div>
                        </div>
                      </div>
                    ))}
                  </Card>
                ))}
              </div>
            </>
          )
        }}
      </Async>
    </div>
  )
}
