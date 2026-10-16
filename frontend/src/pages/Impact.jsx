import { useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading, Tags, shortName, useColumn } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const ROLE = { caller: 'Calls it, may break', relied_on: 'It relies on this' }

// Left to right: services that call the changed one, the changed one, services it relies on. Rules sit underneath.
function DecisionMap({ map }) {
  const svc = map.nodes.filter((n) => ['changed', 'caller', 'relied_on'].includes(n.kind))
  const rules = map.nodes.filter((n) => ['decision', 'review'].includes(n.kind))
  const depthOf = {}
  const incoming = {}
  map.links.filter((l) => l.rel === 'depends_on').forEach((l) => { (incoming[l.to] ||= []).push(l.from) })
  const level = (id, seen = new Set()) => {
    if (depthOf[id] != null) return depthOf[id]
    const n = svc.find((x) => x.id === id)
    if (!n) return 0
    if (n.kind === 'changed') return (depthOf[id] = 0)
    if (seen.has(id)) return 0
    seen.add(id)
    const dir = n.kind === 'caller' ? -1 : 1
    const links = map.links.filter((l) => l.rel === 'depends_on' && (n.kind === 'caller' ? l.from === id : l.to === id))
    const next = links.map((l) => level(n.kind === 'caller' ? l.to : l.from, seen))
    return (depthOf[id] = dir * (1 + Math.max(0, ...next.map(Math.abs))))
  }
  svc.forEach((n) => level(n.id))
  const cols = [...new Set(svc.map((n) => depthOf[n.id] ?? 0))].sort((a, b) => a - b)
  const W = 150, H = 40, GX = 70, GY = 18
  const pos = {}
  cols.forEach((c, ci) => svc.filter((n) => (depthOf[n.id] ?? 0) === c).forEach((n, ri) => { pos[n.id] = { x: 12 + ci * (W + GX), y: 12 + ri * (H + GY) } }))
  const rows = Math.max(...Object.values(pos).map((p) => p.y), 12) + H
  rules.forEach((r, i) => { pos[r.id] = { x: 12 + (i % Math.max(cols.length, 1)) * (W + GX), y: rows + 56 + Math.floor(i / Math.max(cols.length, 1)) * (H + GY) } })
  const width = 24 + cols.length * (W + GX) - GX
  const height = Math.max(...Object.values(pos).map((p) => p.y), 12) + H + 12
  return (
    <svg className="dmap" viewBox={`0 0 ${Math.max(width, 200)} ${height}`} role="img" aria-label="Services that depend on the changed service, and the decisions that govern it">
      <defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a8f98" /></marker></defs>
      {map.links.map((l, i) => {
        const a = pos[l.from], b = pos[l.to]
        if (!a || !b) return null
        const gov = l.rel === 'governs'
        const [x1, y1, x2, y2] = gov ? [a.x + W / 2, a.y, b.x + W / 2, b.y + H] : [a.x + W, a.y + H / 2, b.x, b.y + H / 2]
        return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#8a8f98" strokeWidth="1.2" strokeDasharray={gov ? '4 3' : undefined} markerEnd={gov ? undefined : 'url(#ah)'} />
      })}
      {[...svc, ...rules].map((n) => {
        const p = pos[n.id]
        const changed = n.kind === 'changed', rule = !['changed', 'caller', 'relied_on'].includes(n.kind)
        return (
          <g key={n.id}>
            <rect x={p.x} y={p.y} width={W} height={H} rx={rule ? 20 : 12} fill={changed ? '#155BD0' : '#fff'} stroke={changed ? '#155BD0' : '#d2d6dc'} />
            <text x={p.x + W / 2} y={p.y + H / 2 + 4} textAnchor="middle" fontSize="13" fill={changed ? '#fff' : '#1d1d1f'}>{(rule ? n.label : n.id).slice(0, 20)}</text>
          </g>
        )
      })}
    </svg>
  )
}

function Result({ r }) {
  const col = useColumn()
  const reg = r.evidence || {}
  if (r.status === 'llm_required') return <p className="notice err">The write-up is down; the dependency graph still works. Try again shortly. {r.explanation}</p>
  if (r.status === 'insufficient_evidence') return <p className="notice">{r.explanation}</p>
  return (
    <div className="stack">
      {r.headline && <p className="headline"><Hl text={r.headline.text} k={r.headline.key} /></p>}
      <section className="sect"><h2>What could be affected</h2>
        {r.affected.length === 0 && <p className="muted">Nothing in the graph depends on {r.changed.map((c) => c.service).join(', ')}.</p>}
        <ul className="list plain">
          {r.affected.map((a) => (
            <li key={a.service} style={{ padding: '12px 0' }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <b style={{ fontWeight: 600 }}>{a.service}</b>
                <span className="small muted"><span className={`dot ${a.label === 'verified' ? '' : 'inferred'}`} />{ROLE[a.role]}</span>
              </div>
              <div className="small muted">{a.relationship}</div>
              {a.what_could_break && <p className="text" style={{ margin: '6px 0 0' }}>{a.what_could_break} <span className="small muted">(inferred)</span></p>}
              <div style={{ marginTop: 8 }}><Tags ids={a.evidence} registry={reg} /></div>
            </li>))}
        </ul></section>
      {r.rules.length > 0 && (
        <section className="sect"><h2>Decisions and earlier guidance that apply</h2>
          <div className="stack-s">
            {r.rules.map((x) => (
              <div key={x.id} className="cm">
                <div className="small muted">{x.kind === 'decision' ? `${x.adr}` : 'A reviewer said'}{x.who ? ` · ${shortName(x.who)}` : ''}{x.when ? ` · ${x.when}` : ''}</div>
                <p className="text" style={{ margin: '6px 0' }}>{x.why_it_matters}</p>
                <button type="button" className="pcard" onClick={() => col.open({ id: x.id, quote: x.quote, label: reg[x.id]?.label })}>
                  <span className="pmeta">“ source</span><span className="pq">{x.quote}</span></button>
              </div>))}
          </div></section>)}
      {r.risks.length > 0 && (
        <section className="sect"><h2>Risks</h2>
          {r.risks.map((x, i) => <p key={i} className="text"><span className={`dot ${x.label === 'verified' ? '' : 'inferred'}`} />{x.summary} <Tags ids={x.evidence} registry={reg} /></p>)}</section>)}
      {r.checks.length > 0 && (
        <section className="sect"><h2>Check before merging</h2>
          <ul style={{ paddingLeft: 20, margin: 0 }}>{r.checks.map((x, i) => <li key={i} style={{ marginBottom: 8 }}>{x.check} <Tags ids={x.evidence} registry={reg} /></li>)}</ul></section>)}
      <section className="sect"><h2>Map</h2>
        <DecisionMap map={r.map} />
        <p className="small muted">Arrows point from a service to what it depends on. Dashed lines show which decision or reviewer statement governs a service.</p></section>
      <details className="disc small muted"><summary>What this can and cannot see</summary>
        <ul>{r.limits.map((l) => <li key={l}>{l}</li>)}</ul>
        {r.dropped?.length > 0 && <><p>Left out because no source backs it:</p><ul>{r.dropped.map((d, i) => <li key={i}>{d}</li>)}</ul></>}</details>
    </div>
  )
}

export default function Impact() {
  const [text, setText] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const repos = useAsync(api.overview)
  const names = (repos.data?.repositories || []).map((r) => r.name).slice(0, 4)
  const run = async (q) => {
    q = (q ?? text).trim(); if (q.length < 5) return
    setText(q); setBusy(true); setErr(null)
    try { setRes(await api.impact(q)) } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  return (
    <div className="stack">
      <div><h1>What else could break if this changes?</h1>
        <p className="lede">Services that depend on it come from the dependency graph. The decisions and earlier review comments that apply come with their exact words.</p></div>
      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); run() }}>
        <label className="sr" htmlFor="iq">What are you changing?</label>
        <textarea id="iq" rows={1} value={text} placeholder={`If I change ${names[0] || 'the authentication service'}, what else could break?`} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run() } }} />
        <button className="btn" type="submit" disabled={text.trim().length < 5 || busy}>Check</button>
      </form>
      {!res && !busy && names.length > 0 && <div className="chips">{names.map((n) => <button key={n} className="chip" onClick={() => run(`If I change ${n}, what else could break?`)}>If I change {n}</button>)}</div>}
      {busy && <Reading>Following the dependencies and reading the decisions that apply</Reading>}
      {err && <Problem error={err} />}
      {res && !busy && <Result r={res} />}
    </div>
  )
}
