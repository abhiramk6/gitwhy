import { api } from '../api.js'
import { ago } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const ORDER = ['adr', 'jira_issue', 'github_pr', 'github_comment', 'github_commit', 'doc', 'file']
const NAME = { adr: 'Decisions', jira_issue: 'Tickets and issues', github_pr: 'Pull requests', github_comment: 'Review and issue comments', github_commit: 'Commits', doc: 'Docs and runbooks', file: 'Code files' }

export default function Sources() {
  const s = useAsync(api.sources)
  const runs = useAsync(api.ingestion)
  const d = s.data
  const total = d ? Object.values(d.by_type).reduce((n, v) => n + v.count, 0) : 0
  const newest = d ? Object.values(d.by_type).map((v) => v.latest).filter(Boolean).sort().pop() : null
  const models = d ? Object.entries(d.embeddings) : []
  return (
    <div className="stack">
      <div><h1>What has been read, and what has not.</h1>
        {d && <p className="lede">Read {total.toLocaleString()} items across {Object.keys(d.by_type).length} sources{newest ? `, latest from ${ago(newest)}` : ''}.</p>}</div>
      {s.error && <p className="notice err">{s.error.message}</p>}
      {d && (
        <>
          {models.length === 0 ? <p className="notice">Nothing is indexed for search yet, so search is keyword-only.</p> : models.map(([m, c]) => (
            <div key={m}><div className="row" style={{ justifyContent: 'space-between' }}><span><b style={{ fontWeight: 600 }}>Search index</b> <span className="muted">{m}</span></span><span className="num muted">{c.stored.toLocaleString()} of {c.wanted.toLocaleString()}</span></div>
              <div className="bar" style={{ marginTop: 8 }}><i style={{ width: `${(c.stored / Math.max(c.wanted, 1)) * 100}%` }} /></div></div>
          ))}
          <table className="tbl"><thead><tr><th>{d.organization.name}</th><th className="num">Items</th><th>Newest</th></tr></thead><tbody>
            {ORDER.filter((k) => d.by_type[k]).map((k) => <tr key={k}><td>{NAME[k]}</td><td className="num">{d.by_type[k].count.toLocaleString()}</td><td>{d.by_type[k].latest ? ago(d.by_type[k].latest) : ''}</td></tr>)}</tbody></table>
          <details className="evidence"><summary>See all limits and details</summary>
            <ul style={{ paddingLeft: 20, margin: '0 0 16px' }}>{d.limits.map((l) => <li key={l} style={{ marginBottom: 8 }}>{l}</li>)}</ul>
            {models.map(([m, c]) => <p key={m} className="small muted num">{m}: {c.tiers.map((t) => `${t.label} ${t.stored}/${t.wanted}`).join(', ')}</p>)}
            <p className="small muted">{d.people} people appear in this history. Remembered: {Object.entries(d.facts).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ')}.</p>
            {runs.data?.length > 0 && <p className="small muted">Recent runs: {runs.data.slice(0, 4).map((r) => `${r.source} ${r.mode} ${r.status}`).join('; ')}.</p>}
            <p><a href="#/map">Dependency map</a></p>
          </details>
        </>
      )}
    </div>
  )
}
