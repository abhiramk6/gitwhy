import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

/* ---------- source types: label, glyph, color ---------- */
export const TYPES = {
  github_comment: { label: 'thread', glyph: '❝', color: 'var(--t-thread)' },
  github_pr: { label: 'pull request', glyph: '⇄', color: 'var(--t-pr)' },
  jira_issue: { label: 'ticket', glyph: '◫', color: 'var(--t-ticket)' },
  adr: { label: 'decision', glyph: '§', color: 'var(--t-decision)' },
  file: { label: 'code', glyph: '‹›', color: 'var(--t-code)' },
  github_commit: { label: 'commit', glyph: '●', color: 'var(--t-commit)' },
  doc: { label: 'doc', glyph: '¶', color: 'var(--t-doc)' },
  dependency: { label: 'dependency', glyph: '→', color: 'var(--t-code)' },
  statistic: { label: 'history', glyph: '∑', color: 'var(--t-commit)' },
  fact: { label: 'remembered', glyph: '◆', color: 'var(--t-fact)' },
}
const typeOf = (t) => TYPES[t] || TYPES.fact
export const shortName = (who) => (who ? who.split('.')[0].replace(/^./, (c) => c.toUpperCase()) : null)
export const ago = (iso) => {
  if (!iso) return ''
  const d = new Date(iso); if (Number.isNaN(+d)) return ''
  const days = Math.round((Date.now() - d) / 864e5)
  if (days < 0) return d.toISOString().slice(0, 10)
  if (days < 45) return d.toLocaleDateString('en', { month: 'short', day: 'numeric' })
  return d.toLocaleDateString('en', { month: 'short', year: 'numeric' })
}

/* ---------- tag metadata cache (who/when for any evidence id) ---------- */
const cache = new Map()
export function useTagMeta(ids) {
  const key = (ids || []).join('|')
  const [, bump] = useState(0)
  useEffect(() => {
    const need = (ids || []).filter((i) => !cache.has(i))
    if (!need.length) return
    let live = true
    api.tags(need).then((m) => { need.forEach((i) => cache.set(i, m[i] || null)); if (live) bump((n) => n + 1) })
      .catch(() => { need.forEach((i) => cache.set(i, null)); if (live) bump((n) => n + 1) })
    return () => { live = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return (id) => cache.get(id) || null
}

/* ---------- provenance column context ---------- */
const Ctx = createContext(null)
export const useColumn = () => useContext(Ctx)
export function ColumnProvider({ children }) {
  const [sel, setSel] = useState(null) // { id, label, quote }
  const open = useCallback((s) => setSel(s), [])
  const close = useCallback(() => setSel(null), [])
  useEffect(() => {
    const on = (e) => { if (e.key === 'Escape') setSel(null) }
    window.addEventListener('keydown', on); return () => window.removeEventListener('keydown', on)
  }, [])
  const v = useMemo(() => ({ sel, open, close }), [sel, open, close])
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>
}

/* ---------- Tag: glyph, name, date ---------- */
export function Tag({ id, meta, quote, label, land }) {
  const col = useColumn()
  const m = meta || null
  const t = typeOf(m?.type)
  const name = shortName(m?.who) || (m?.type === 'statistic' ? (m.title || '').split('/').pop() : t.label)
  const on = col?.sel?.id === id
  return (
    <button type="button" className={`tag${on ? ' on' : ''}${land ? ' land' : ''}${m?.status === 'superseded' ? ' superseded' : ''}`}
      style={{ '--tc': t.color, animationDelay: land ? `${land * 70}ms` : undefined }}
      title={m?.title || label || id} onClick={() => col?.open({ id, label, quote })}>
      <span className="g" aria-hidden>{t.glyph}</span>
      <span className="n">{name}</span>
      {m?.when && <span className="d">{ago(m.when)}</span>}
      <span className="sr">{t.label}: {m?.title || label || id}</span>
    </button>
  )
}

export function Tags({ ids, registry, quote, land, max = 4 }) {
  const meta = useTagMeta(ids)
  const [all, setAll] = useState(false)
  const shown = all ? ids || [] : (ids || []).slice(0, max)
  return <>{shown.map((id, i) => <Tag key={id} id={id} meta={meta(id) && { ...meta(id), status: registry?.[id]?.status }}
    label={registry?.[id]?.label} quote={quote} land={land ? i + 1 : 0} />)}
    {!all && (ids || []).length > max && <button type="button" className="tag" onClick={() => setAll(true)}><span className="n">+{ids.length - max} more</span></button>}</>
}

/* ---------- strata: one band per source, oldest at the bottom ---------- */
export function Strata({ ids }) {
  const meta = useTagMeta(ids)
  const bands = (ids || []).map((id) => ({ id, m: meta(id) })).sort((a, b) => (b.m?.when || '').localeCompare(a.m?.when || ''))
  return (
    <div className="strata" aria-hidden>
      {bands.map((b, i) => <i key={b.id} style={{ '--tc': typeOf(b.m?.type).color, animationDelay: `${i * 80}ms` }} />)}
    </div>
  )
}
export function spanLine(ids, meta) {
  const ms = (ids || []).map(meta).filter(Boolean)
  const dates = ms.map((m) => m.when).filter(Boolean).sort()
  const kinds = [...new Set(ms.map((m) => typeOf(m.type).label))]
  if (!ms.length) return ''
  const age = (iso) => { const d = Math.round((Date.now() - new Date(iso)) / 864e5); return d < 45 ? `${Math.max(d, 1)} days ago` : `${Math.round(d / 30)} months ago` }
  const range = dates.length ? `, the oldest from ${age(dates[0])}` : ''
  return `${ms.length} ${ms.length === 1 ? 'source' : 'sources'}${range} (${kinds.join(', ')})`
}

/* ---------- Provenance Column ---------- */
function Words({ text, quote }) {
  if (!quote || !text) return <div className="words">{text}</div>
  const norm = (s) => s.toLowerCase().replace(/[`*]/g, '')
  const i = norm(text).indexOf(norm(quote))
  if (i < 0) return <div className="words">{text}</div>
  return <div className="words">{text.slice(0, i)}<mark>{text.slice(i, i + quote.length)}</mark>{text.slice(i + quote.length)}</div>
}

export function Column({ go }) {
  const { sel, close } = useColumn()
  const meta = useTagMeta(sel ? [sel.id] : [])
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const m = sel ? meta(sel.id) : null
  const rid = m?.record
  useEffect(() => {
    setData(null); setErr(null)
    if (!rid) return
    let live = true
    api.provenance(rid).then((d) => live && setData(d)).catch((e) => live && setErr(e))
    return () => { live = false }
  }, [rid])
  if (!sel) return null
  const t = typeOf(data?.type || m?.type)
  return (
    <aside className="col" aria-label="Where this comes from">
      <header>
        <div>
          <div className="meta"><span style={{ color: t.color, fontWeight: 600 }}>{t.glyph} {t.label}</span></div>
          <h3>{data?.title || sel.label || m?.title || sel.id}</h3>
        </div>
        <button className="x" onClick={close} aria-label="Close (Esc)">×</button>
      </header>
      <div className="body stack">
        {sel.label && (data?.type !== 'github_comment') && sel.label !== data?.title && <p className="small muted">{sel.label}</p>}
        {!rid && <p className="notice">{m ? 'This is derived from other records, so there is no single original text.' : 'This source is no longer available. The citation was captured when the answer was written.'}</p>}
        {err && <p className="notice err">Could not load the original: {err.message}</p>}
        {rid && !data && !err && <p className="reading"><b />Opening the original</p>}
        {data && (
          <>
            <div className="meta">
              {data.author && <span>by <b>{shortName(data.author)}</b></span>}
              {data.date && <span className="num">{ago(data.date)} ({data.date})</span>}
              {data.path && <code>{data.path}</code>}
              {data.url && <a href={data.url} target="_blank" rel="noreferrer">Open at source</a>}
            </div>
            <Words text={data.body} quote={sel.quote} />
            {data.thread.length > 1 && (
              <section>
                <h3 style={{ marginBottom: 10 }}>The thread around it</h3>
                <ul className="core" style={{ '--tc': 'var(--t-thread)' }}>
                  {data.thread.map((c) => (
                    <li key={c.id} className={c.current ? 'cur' : ''} style={{ '--tc': 'var(--t-thread)' }}>
                      <div className="when"><b>{shortName(c.who)}</b> · {ago(c.when)}{c.kind ? ` · ${c.kind.replace('_', ' ')}` : ''}</div>
                      {c.current ? <div className="small muted">This is the comment above.</div> : <div className="words" style={{ fontSize: 15 }}>{c.body}</div>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {data.related.length > 0 && (
              <section>
                <h3 style={{ marginBottom: 10 }}>Where it sits</h3>
                <ul className="core">
                  {data.related.map((r) => (
                    <li key={r.id} style={{ '--tc': typeOf(r.kind === 'pull_request' ? 'github_pr' : 'jira_issue').color }}>
                      <div className="when">{r.who ? `${shortName(r.who)} · ` : ''}{ago(r.when)}</div>
                      <div className="what">{r.title}</div>
                      {r.files && <div className="small muted">{r.files.join(', ')}</div>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <div className="row">
              {m?.fact_type === 'review_guidance' && <button className="btn quiet small" onClick={() => go('memory')}>See this standard's history</button>}
              {data.type === 'file' && <button className="btn quiet small" onClick={() => go(`trace?f=${encodeURIComponent(data.source_id)}`)}>Trace this file</button>}
              {data.type === 'github_comment' && <button className="btn quiet small" onClick={() => go('memory')}>Standards from this thread</button>}
            </div>
          </>
        )}
      </div>
    </aside>
  )
}

/* ---------- highlighted key phrase ---------- */
export function Hl({ text, k }) {
  const t = text || ''
  const i = k ? t.toLowerCase().indexOf(k.toLowerCase()) : -1
  if (i < 0) return <>{t}</>
  return <>{t.slice(0, i)}<mark className="key">{t.slice(i, i + k.length)}</mark>{t.slice(i + k.length)}</>
}

/* ---------- proof: the exact words, with who said them and when ---------- */
export function Proof({ items }) {
  const col = useColumn()
  const meta = useTagMeta((items || []).map((p) => p.id))
  const [all, setAll] = useState(false)
  const shown = all ? items : (items || []).slice(0, 3)
  if (!items?.length) return null
  return (
    <div className="proof" aria-label="Proof">
      {shown.map((p, i) => {
        const m = meta(p.id); const t = typeOf(m?.type)
        return (
          <button key={p.id} type="button" className="pcard" style={{ '--tc': t.color, animationDelay: `${i * 90}ms` }}
            onClick={() => col.open({ id: p.id, quote: p.quote, label: m?.title })}>
            <span className="pmeta"><span style={{ color: t.color }}>{t.glyph}</span> <b>{shortName(m?.who) || t.label}</b> <span className="d">{ago(m?.when)}</span> <span className="small muted">{t.label}</span></span>
            <span className="words pq">“{p.quote}”</span>
          </button>
        )
      })}
      {!all && items.length > 3 && <button type="button" className="btn quiet small" onClick={() => setAll(true)}>{items.length - 3} more proofs</button>}
    </div>
  )
}

/* ---------- small shared bits ---------- */
export function Reading({ children }) { return <p className="reading" role="status"><b />{children}</p> }
export function Problem({ error }) {
  const quota = /quota|429|exhaust/i.test(error?.message || '')
  return (
    <p className="notice err" role="alert">
      {error?.status === 401 ? 'This action needs the demo token. Set it from the key icon in the top bar.' :
        quota ? `The model quota is used up for now (${error.message}). Everything that does not need a model still works.` :
          error?.message || 'Something went wrong.'}
    </p>
  )
}
export function useRoute() {
  const read = () => { const h = window.location.hash.replace(/^#\/?/, ''); const [page, qs] = (h || 'ask').split('?'); return { page, q: new URLSearchParams(qs || '') } }
  const [r, setR] = useState(read)
  useEffect(() => { const on = () => setR(read()); window.addEventListener('hashchange', on); return () => window.removeEventListener('hashchange', on) }, [])
  return r
}
export const go = (to) => { window.location.hash = `#/${to}` }
export const copyText = (t) => { try { navigator.clipboard.writeText(t) } catch { /* clipboard unavailable */ } }
