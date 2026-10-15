import { useState } from 'react'
import { api } from '../api.js'
import { Async, Badge, Card, Chip, fmt, useAsync } from '../components.jsx'

const STATUSES = ['', 'active', 'candidate', 'superseded', 'rejected']

function Commands({ onDone }) {
  const [author, setAuthor] = useState('ines.kowalski')
  const [mem, setMem] = useState('')
  const [rule, setRule] = useState('ADR-004')
  const [reason, setReason] = useState('')
  const [approver, setApprover] = useState('')
  const [temp, setTemp] = useState(true)
  const [msg, setMsg] = useState(null)
  const wrap = async (fn) => {
    try { const r = await fn(); setMsg(r.created ? `Recorded as ${r.status}.` : 'Already recorded (no duplicate created).'); onDone() }
    catch (e) { setMsg(e.status === 401 ? 'Needs the demo token (sidebar).' : e.message) }
  }
  return (
    <Card title="Commands">
      <label>Author <input value={author} onChange={(e) => setAuthor(e.target.value)} /></label>
      <h4>/remember</h4>
      <div className="row"><input value={mem} onChange={(e) => setMem(e.target.value)} placeholder="Something the organization should remember…" />
        <button disabled={mem.trim().length < 3} onClick={() => wrap(() => api.remember({ text: mem, author }))}>Remember</button></div>
      <h4>/override</h4>
      <div className="row">
        <input value={rule} onChange={(e) => setRule(e.target.value)} placeholder="ADR-004" style={{ maxWidth: 110 }} />
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" />
      </div>
      <div className="row">
        <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Approver (optional)" />
        <label className="inline"><input type="checkbox" checked={temp} onChange={(e) => setTemp(e.target.checked)} /> temporary</label>
        <button disabled={!/^ADR-\d+$/.test(rule) || reason.trim().length < 5}
                onClick={() => wrap(() => api.override({ rule, reason, author, temporary: temp, approver: approver || null }))}>Record override</button>
      </div>
      {msg && <div className="muted" role="status">{msg}</div>}
    </Card>
  )
}

export default function Knowledge() {
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const st = useAsync(() => api.knowledge({ ...(status && { status }), ...(type && { fact_type: type }) }), [status, type])
  const [err, setErr] = useState(null)
  const curate = async (id, s) => {
    try { setErr(null); await api.setFactStatus(id, s); st.reload() } catch (e) { setErr(e.status === 401 ? 'Curation needs the demo token (sidebar).' : e.message) }
  }
  const types = st.data ? [...new Set(st.data.map((f) => f.fact_type))] : []
  return (
    <div className="page">
      <h1>Knowledge inspector</h1>
      <p className="muted">Raw evidence is always kept. Only validated, sourced facts become <b>active</b>; everything else stays a reviewable candidate.</p>
      <div className="filters">
        {STATUSES.map((s) => <Chip key={s || 'all'} active={status === s} onClick={() => setStatus(s)}>{s || 'all statuses'}</Chip>)}
        <span className="sep" />
        <Chip active={type === ''} onClick={() => setType('')}>all types</Chip>
        {types.map((t) => <Chip key={t} active={type === t} onClick={() => setType(t)}>{t}</Chip>)}
      </div>
      {err && <div className="state error" role="alert">{err}</div>}
      <div className="grid-graph">
        <Card title="Facts and decisions">
          <Async state={st} empty="No facts match these filters.">
            {(rows) => (
              <table>
                <thead><tr><th>Claim</th><th>Type</th><th>Evidence</th><th>Status</th><th>Observed</th><th /></tr></thead>
                <tbody>
                  {rows.map((f) => (
                    <tr key={f.id} className={f.status === 'superseded' ? 'dim' : ''}>
                      <td><Badge kind={f.label} /> {f.summary}
                        <div className="muted">{f.repo ? `${f.repo} · ` : ''}scope {f.scope} · {f.source_type} {f.source_id}
                          {f.source_url && <> · <a href={f.source_url} target="_blank" rel="noreferrer">source</a></>}
                          {f.author ? ` · by ${f.author}` : ''}{f.superseded_by ? ` · superseded by #${f.superseded_by}` : ''}</div></td>
                      <td>{f.fact_type}</td><td>{f.evidence_type}<div className="muted">{Math.round(f.confidence * 100)}%</div></td>
                      <td>{f.status}</td><td>{fmt(f.observed_at)}</td>
                      <td className="actions">
                        {f.status === 'candidate' && <><button onClick={() => curate(f.id, 'active')}>Promote</button>
                          <button className="ghost" onClick={() => curate(f.id, 'rejected')}>Reject</button></>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Async>
        </Card>
        <Commands onDone={st.reload} />
      </div>
    </div>
  )
}
