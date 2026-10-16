import { api } from '../api.js'
import { TYPES, ago } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const ORDER = ['adr', 'jira_issue', 'github_pr', 'github_comment', 'github_commit', 'doc', 'file']
const NAME = { adr: 'Decisions', jira_issue: 'Tickets and issues', github_pr: 'Pull requests', github_comment: 'Review and issue comments', github_commit: 'Commits', doc: 'Docs and runbooks', file: 'Code files' }

export default function Sources() {
  const s = useAsync(api.sources)
  const runs = useAsync(api.ingestion)
  const d = s.data
  return (
    <div className="stack">
      <div><h1>What has been read, and what has not</h1>
        <p className="lede">The product is only as deep as these sources. Counts, freshness, the embedding model in use and any limits are stated here rather than assumed.</p></div>
      {s.error && <p className="notice err">{s.error.message}</p>}
      {d && (
        <>
          <section className="sect"><h2>{d.organization.name}</h2>
            <table className="tbl"><thead><tr><th>Source</th><th className="num">Records</th><th>Newest</th></tr></thead><tbody>
              {ORDER.filter((k) => d.by_type[k]).map((k) => (
                <tr key={k}><td><span style={{ color: (TYPES[k] || TYPES.fact).color, marginRight: 8 }}>{(TYPES[k] || TYPES.fact).glyph}</span>{NAME[k]}</td>
                  <td className="num">{d.by_type[k].count.toLocaleString()}</td><td className="num">{d.by_type[k].latest ? ago(d.by_type[k].latest) : ''}</td></tr>
              ))}</tbody></table>
            <p className="small muted" style={{ marginTop: 10 }}>{d.people} people appear in this history. Remembered facts: {Object.entries(d.facts).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ')}.</p>
          </section>
          <section className="sect"><h2>Search index</h2>
            {Object.keys(d.embeddings).length === 0 && <p className="notice">No vectors yet: search is keyword-only until an embedding model has indexed the sources.</p>}
            {Object.entries(d.embeddings).map(([m, c]) => (
              <div key={m} style={{ marginBottom: 16 }}>
                <p><b>{m}</b> <span className="muted num">{c.stored.toLocaleString()} of {c.wanted.toLocaleString()} chunks</span></p>
                <div className="bar" style={{ margin: '6px 0 8px' }}><i style={{ width: `${(c.stored / Math.max(c.wanted, 1)) * 100}%` }} /></div>
                <p className="small muted num">{c.tiers.map((t) => `${t.label} ${t.stored}/${t.wanted}`).join(', ')}</p>
              </div>
            ))}
          </section>
          <section className="sect"><h2>Limits, stated plainly</h2><ul style={{ paddingLeft: 18, margin: 0 }}>{d.limits.map((l) => <li key={l} style={{ marginBottom: 6 }}>{l}</li>)}</ul></section>
        </>
      )}
      {runs.data?.length > 0 && (
        <section className="sect"><h2>Recent ingestion runs</h2>
          <table className="tbl"><thead><tr><th>Source</th><th>Mode</th><th>Status</th><th className="num">Seen</th><th className="num">New</th></tr></thead><tbody>
            {runs.data.slice(0, 6).map((r) => <tr key={r.id}><td>{r.source}</td><td>{r.mode}</td><td>{r.status}</td><td className="num">{r.records_seen}</td><td className="num">{r.records_new}</td></tr>)}</tbody></table>
        </section>
      )}
    </div>
  )
}
