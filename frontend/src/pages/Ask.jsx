import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Proof, Reading, Tags, copyText, spanLine, useTagMeta } from '../ui.jsx'
import { useAsync } from '../components.jsx'

function Rate({ id }) {
  const [state, setState] = useState(null)
  const [onb, setOnb] = useState(false)
  if (!id) return null
  const send = async (correct) => { try { await api.feedback({ event_id: id, resolved: correct === 'yes', correct, onboarding: onb }); setState('done') } catch { setState('error') } }
  if (state === 'done') return <p className="small muted">Thanks, recorded.</p>
  return (
    <div className="row small" style={{ gap: 12, flexWrap: 'wrap' }}>
      <span className="muted">Did this answer your question?</span>
      <button className="btn quiet small" onClick={() => send('yes')}>Yes, correct</button>
      <button className="btn quiet small" onClick={() => send('no')}>No, wrong or unhelpful</button>
      <label className="muted"><input type="checkbox" checked={onb} onChange={(e) => setOnb(e.target.checked)} /> I'm new here (onboarding question)</label>
      {state === 'error' && <span className="muted">Could not save that.</span>}
    </div>
  )
}

function Answer({ res }) {
  const ids = (res.citations || []).map((c) => c.id)
  const meta = useTagMeta(ids)
  const reg = Object.fromEntries((res.citations || []).map((c) => [c.id, { label: c.title, status: c.status }]))
  const md = [res.headline ? `**${res.headline.text}**` : '', ...res.answer.map((a) => `${a.text} ${a.cites.map((c) => `[${(reg[c]?.label || c)}]`).join('')}`),
    '', ...(res.citations || []).map((c) => `- ${c.title}${c.url ? ` (${c.url})` : ''}`)].join('\n')
  const trust = (res.citations || []).some((c) => c.status === 'superseded') ? 'superseded' : (res.citations || []).every((c) => c.label !== 'inferred') ? '' : 'inferred'
  return (
    <div className="stack-s">
      {res.status === 'insufficient' && <p className="notice">No source backs this up, so we're not saying it. {res.note}</p>}
      {res.status === 'llm_required' && <p className="notice err">The write-up is down; search still works. Try again shortly. {res.note}</p>}
      {res.status === 'partial' && <p className="notice">Part of this is supported by the sources. The rest is left out, not guessed.</p>}
      {res.headline && <p className="headline"><Hl text={res.headline.text} k={res.headline.key} /></p>}
      <Proof items={res.proof} />
      {res.answer.length > 0 && (
        <div className="answer">
          {res.answer.slice(0, 2).map((a, i) => <p key={i}><Hl text={a.text} k={a.key} /> <Tags ids={a.cites} registry={reg} /></p>)}
          {res.answer.length > 2 && (
            <details className="disc"><summary>More detail ({res.answer.length - 2})</summary>
              {res.answer.slice(2).map((a, i) => <p key={i}><Hl text={a.text} k={a.key} /> <Tags ids={a.cites} registry={reg} /></p>)}</details>
          )}
        </div>
      )}
      {res.answer.length > 0 && <p className="span-line"><span className={`dot ${trust}`} />{trust === 'inferred' ? 'Inferred in part, treat as a lead. ' : trust === 'superseded' ? 'Includes a replaced decision. ' : 'Backed by the sources themselves. '}{spanLine(ids, meta)}.</p>}
      {res.dropped?.length > 0 && (
        <details className="disc small muted"><summary>{res.dropped.length} statement{res.dropped.length > 1 ? 's' : ''} left out: no source backs {res.dropped.length > 1 ? 'them' : 'it'} up</summary>
          <ul>{res.dropped.map((d, i) => <li key={i}>{d.text}</li>)}</ul></details>
      )}
      {res.answer.length > 0 && <div><button className="btn quiet small" onClick={() => copyText(md)}>Copy with sources</button></div>}
      {res.answer.length > 0 && <Rate id={res.event_id} />}
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
  }
  const bt = src.data?.by_type || {}
  const total = Object.values(bt).reduce((n, v) => n + v.count, 0)
  return (
    <div className="stack">
      <div>
        <h1>Ask what your team already decided.</h1>
        {turns.length === 0 && <p className="lede">Every answer shows the review thread, ticket, decision or code it came from, in the words of the people who wrote it.{total ? ` ${total.toLocaleString()} records read.` : ''}</p>}
      </div>
      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <label className="sr" htmlFor="q">Your question</label>
        <textarea id="q" rows={1} value={text} placeholder="How should I paginate a new list endpoint?" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} />
        <button className="btn" type="submit" disabled={text.trim().length < 3}>Ask</button>
      </form>
      {turns.length === 0 && (
        <div className="stack-s">
          <div className="chips">{(starters.data || []).map((s) => <button key={s} className="chip" onClick={() => submit(s)}>{s}</button>)}</div>
          <div className="legend" style={{ marginTop: 24 }}>
            <span><span className="dot" />Backed by the source itself</span><span><span className="dot inferred" />Inferred, treat as a lead</span><span><span className="dot contradicted" />Replaced, shown as history</span>
          </div>
        </div>
      )}
      {turns.map((t, i) => (
        <section key={i} className="sect">
          <p className="q">{t.q}</p>
          {t.loading && <Reading>Reading {total.toLocaleString() || 'the'} records and weighing the best sources</Reading>}
          {t.err && <Problem error={t.err} />}
          {t.res && <Answer res={t.res} />}
          {t.res?.follow_ups?.length > 0 && <div className="chips" style={{ marginTop: 20 }}>{t.res.follow_ups.map((f) => <button key={f} className="chip" onClick={() => submit(f)}>{f}</button>)}</div>}
        </section>
      ))}
      <div ref={end} />
    </div>
  )
}
