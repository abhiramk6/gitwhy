import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { Async, Badge, Card, Chip, useAsync } from '../components.jsx'

const TYPE_ORDER = ['person', 'service', 'package', 'endpoint', 'decision']
const REL_STYLE = { depends_on: '#4f7cff', applies_to: '#8a6bd6', owns: '#2a9d8f', supersedes: '#d9622b', calls_http: '#4f7cff', defined_in: '#9aa3b2' }
const W = 920, ROW_H = 110, PER_LINE = 7

// One band per entity type; large groups (e.g. 30+ packages in a real repository set) wrap onto extra lines.
function layout(nodes) {
  const pos = {}
  let y = 50
  const types = [...new Set([...TYPE_ORDER, ...nodes.map((n) => n.type)])]
  types.forEach((t) => {
    const list = nodes.filter((n) => n.type === t)
    for (let start = 0; start < list.length; start += PER_LINE) {
      const line = list.slice(start, start + PER_LINE)
      line.forEach((n, i) => { pos[n.id] = { x: ((i + 0.5) * W) / PER_LINE + ((PER_LINE - line.length) * W) / (2 * PER_LINE), y } })
      y += ROW_H - 20
    }
    if (list.length) y += 30
  })
  return pos
}

export default function GraphPage() {
  const g = useAsync(api.graph)
  const [types, setTypes] = useState({ service: true, decision: true, person: true, package: true, endpoint: false })
  const [rels, setRels] = useState({ depends_on: true, applies_to: true, owns: true, supersedes: true, calls_http: false, defined_in: false })
  const [sel, setSel] = useState(null)
  const detail = useAsync(() => (sel ? api.entity(sel) : Promise.resolve(null)), [sel])

  const view = useMemo(() => {
    if (!g.data) return null
    const nodes = g.data.nodes.filter((n) => types[n.type])
    const ids = new Set(nodes.map((n) => n.id))
    const edges = g.data.edges.filter((e) => rels[e.rel] && ids.has(e.src) && ids.has(e.dst))
    return { nodes, edges, pos: layout(nodes) }
  }, [g.data, types, rels])

  return (
    <div className="page legacy">
      <h1>Organization graph</h1>
      <div className="filters">
        {Object.keys(types).map((t) => <Chip key={t} active={types[t]} onClick={() => setTypes({ ...types, [t]: !types[t] })}>{t}</Chip>)}
        <span className="sep" />
        {Object.keys(rels).map((r) => <Chip key={r} active={rels[r]} onClick={() => setRels({ ...rels, [r]: !rels[r] })}>{r}</Chip>)}
      </div>
      <div className="grid-graph">
        <Card title="Entities and relationships" right={<span className="muted">solid = verified · dashed = inferred</span>}>
          <Async state={g} empty="The graph is empty. Run ingestion first.">
            {() => (
              <svg viewBox={`0 0 ${W} ${Math.max(...Object.values(view.pos).map((p) => p.y), 100) + 60}`} role="img" aria-label="Knowledge graph">
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
                  </marker>
                </defs>
                {view.edges.map((e) => {
                  const a = view.pos[e.src], b = view.pos[e.dst]
                  if (!a || !b) return null
                  return (
                    <line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={REL_STYLE[e.rel] || '#999'} strokeWidth="2"
                          strokeDasharray={e.label === 'verified' ? undefined : '6 4'} markerEnd="url(#arrow)" opacity="0.8">
                      <title>{`${e.rel} · ${e.evidence_type} · ${e.status}`}</title>
                    </line>
                  )
                })}
                {view.nodes.map((n) => {
                  const p = view.pos[n.id]
                  return (
                    <g key={n.id} transform={`translate(${p.x},${p.y})`} className={`node ${n.type} ${sel === n.id ? 'sel' : ''}`}
                       onClick={() => setSel(n.id)} tabIndex={0} role="button" aria-label={`${n.type} ${n.name}`}
                       onKeyDown={(e) => (e.key === 'Enter' ? setSel(n.id) : null)}>
                      <rect x={-62} y={-17} width={124} height={34} rx={8} />
                      <text textAnchor="middle" dy="5">{n.name.length > 17 ? n.name.slice(0, 16) + '…' : n.name}</text>
                    </g>
                  )
                })}
              </svg>
            )}
          </Async>
        </Card>
        <Card title="Evidence">
          {!sel && <div className="state">Select a node to inspect its relationships and facts.</div>}
          {sel && (
            <Async state={detail}>
              {(d) => d && (
                <div>
                  <h4>{d.name} <span className="muted">{d.type}{d.repo ? ` · ${d.repo}` : ''}</span></h4>
                  {['outbound', 'inbound'].map((dir) => (
                    <div key={dir}>
                      <div className="muted">{dir === 'outbound' ? 'Points to' : 'Referenced by'}</div>
                      {d[dir].length === 0 && <div className="muted">none</div>}
                      {d[dir].filter((e) => e.rel === 'part_of').length > 0 && (
                        <div className="muted">{d[dir].filter((e) => e.rel === 'part_of').length} modules (part_of) — see Knowledge for sources</div>
                      )}
                      {d[dir].filter((e) => e.rel !== 'part_of').map((e) => (
                        <div key={e.id} className="alert">
                          <Badge kind={['structural', 'explicit'].includes(e.evidence_type) && e.status === 'active' ? 'verified' : 'inferred'} />
                          <div><button className="link" onClick={() => setSel(e.other_id)}>{e.other}</button>
                            <div className="muted">{e.rel} · {e.evidence_type}{e.source ? ` · ${e.source}` : ''}</div></div>
                        </div>
                      ))}
                    </div>
                  ))}
                  {d.facts.length > 0 && <div className="muted">Facts</div>}
                  {d.facts.map((f) => (
                    <div key={f.id} className="alert"><Badge kind={f.evidence_type !== 'inferred' && f.status === 'active' ? 'verified' : 'inferred'} />
                      <div>{f.summary}<div className="muted">{f.fact_type} · {f.status} · {f.source_type} {f.source_id}</div></div></div>
                  ))}
                </div>
              )}
            </Async>
          )}
        </Card>
      </div>
    </div>
  )
}
