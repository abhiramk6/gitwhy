import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Proof, Reading, Strata, Tags, copyText, spanLine, useTagMeta } from '../ui.jsx'
import { useAsync } from '../components.jsx'

function Answer({ res }) {
  const ids = (res.citations || []).map((c) => c.id)
  const meta = useTagMeta(ids)
  const reg = Object.fromEntries((res.citations || []).map((c) => [c.id, { label: c.title, status: c.status }]))
  const md = [res.headline ? `**${res.headline.text}**` : '', ...res.answer.map((a) => `${a.text} ${a.cites.map((c) => `[${(reg[c]?.label || c)}]`).join('')}`),
    '', ...(res.citations || []).map((c) => `- ${c.title}${c.url ? ` (${c.url})` : ''}`)].join('\n')
  return (
    <div className="turn">
      <Strata ids={ids} />
      <div className="stack-s">
        {res.status === 'insufficient' && <p className="notice">There is not enough evidence to answer this. {res.note || 'Nothing in the sources states it, so nothing is guessed.'}</p>}
        {res.status === 'llm_required' && <p className="notice err">Asking needs a language model and none is available. Search over the sources still works. {res.note}</p>}
        {res.status === 'partial' && <p className="notice">Part of the answer is supported by the sources. The rest is left out, not guessed.</p>}
        {res.headline && <p className="headline"><Hl text={res.headline.text} k={res.headline.key} /></p>}
        <Proof items={res.proof} />
        <div className="answer">
          {res.answer.map((a, i) => <p key={i}><Hl text={a.text} k={a.key} /> <Tags ids={a.cites} registry={reg} land={i + 1} /></p>)}
        </div>
        {res.answer.length > 0 && <p className="span-line">{spanLine(ids, meta)}. Considered {res.considered} candidates.</p>}
        {res.dropped?.length > 0 && (
          <details className="small muted"><summary>{res.dropped.length} statement{res.dropped.length > 1 ? 's' : ''} left out because no source supports {res.dropped.length > 1 ? 'them' : 'it'}</summary>
            <ul>{res.dropped.map((d, i) => <li key={i}>{d.text}</li>)}</ul></details>
        )}
        {res.answer.length > 0 && <div><button className="btn quiet small" onClick={() => copyText(md)}>Copy with sources</button></div>}
      </div>
    </div>
  )
}

export default function Ask() {
  const [text, setText] = useState('')
  const [turns, setTurns] = useState([])
  const starters = useAsync(api.starters)
  const src = useAsync(api.sources)
  const end = useRef(null)
  useEffect(() => { const on = (e) => { if (e.key === '/' && document.activeElement.tagName !== 'TEXTAREA') { e.preventDefault(); document.getElementById('q')?.focus() } }; window.addEventListener('keydown', on); return () => window.removeEventListener('keydown', on) }, [])
  const submit = async (q) => {
    q = (q ?? text).trim(); if (q.length < 3) return
    const history = turns.filter((t) => t.res?.answer?.length).map((t) => ({ question: t.q, text: t.res.answer.map((a) => a.text).join(' ') }))
    setText(''); const i = turns.length
    setTurns((t) => [...t, { q, loading: true }])
    try { const res = await api.ask(q, history); setTurns((t) => t.map((x, k) => (k === i ? { q, res } : x))) }
    catch (err) { setTurns((t) => t.map((x, k) => (k === i ? { q, err } : x))) }
    setTimeout(() => end.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }
  const bt = src.data?.by_type || {}
  const read = [['github_pr', 'PRs'], ['github_comment', 'review comments'], ['jira_issue', 'tickets'], ['adr', 'decisions'], ['file', 'code files']]
    .filter(([k]) => bt[k]).map(([k, l]) => `${bt[k].count.toLocaleString()} ${l}`).join(', ')
  return (
    <div className="stack">
      <div>
        <h1>Ask what the team already knows</h1>
        <p className="lede">Every statement carries the review thread, ticket, decision or code it came from. Click a tag to read the original words.</p>
        {read && <p className="small muted" style={{ marginTop: 6 }}>Read so far: {read}.</p>}
      </div>
      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <label className="sr" htmlFor="q">Your question</label>
        <textarea id="q" rows={1} value={text} placeholder="e.g. How should I paginate a new list endpoint?" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} />
        <button className="btn" type="submit" disabled={text.trim().length < 3}>Ask</button>
      </form>
      {turns.length === 0 && (
        <div className="stack-s">
          <p className="small muted">Questions this history can answer:</p>
          <div className="chips">{(starters.data || []).map((s) => <button key={s} className="chip" onClick={() => submit(s)}>{s}</button>)}</div>
          <div className="legend" style={{ marginTop: 16 }}>
            <span><span className="mark" />verified by the source itself</span><span><span className="mark inferred" />inferred, treat as a lead</span><span><span className="mark superseded" />replaced, shown only as history</span>
          </div>
        </div>
      )}
      {turns.map((t, i) => (
        <section key={i} className="sect">
          <p className="q">{t.q}</p>
          {t.loading && <Reading>Reading {Object.values(bt).reduce((n, v) => n + v.count, 0).toLocaleString() || 'the'} records and weighing the best sources</Reading>}
          {t.err && <Problem error={t.err} />}
          {t.res && <Answer res={t.res} />}
          {t.res?.follow_ups?.length > 0 && <div className="chips" style={{ marginTop: 14 }}>{t.res.follow_ups.map((f) => <button key={f} className="chip" onClick={() => submit(f)}>{f}</button>)}</div>}
        </section>
      ))}
      <div ref={end} />
    </div>
  )
}
