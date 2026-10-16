import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Hl, Problem, Reading } from '../ui.jsx'
import { useAsync } from '../components.jsx'

const fmt = (s) => (s == null ? 'not yet' : s < 1 ? 'under 1 s' : s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`)

function Stopwatch({ running }) {
  const t0 = useRef(null)
  const [, tick] = useState(0)
  useEffect(() => { if (!running) return undefined; t0.current = Date.now(); const id = setInterval(() => tick((n) => n + 1), 500); return () => clearInterval(id) }, [running])
  return <span className="num">{running && t0.current ? Math.floor((Date.now() - t0.current) / 1000) : 0} s</span>
}

function TimedTask({ starters, onDone }) {
  const [task, setTask] = useState('')
  const [step, setStep] = useState('pick') // pick | manual | ask | asking | judge | done
  const started = useRef(0)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const secs = () => Math.round((Date.now() - started.current) / 100) / 10
  const save = async (arm, found) => { try { await api.timedTask({ task, arm, seconds: secs(), found }) } catch (e) { setErr(e) } }
  const start = (next) => { started.current = Date.now(); setStep(next) }
  const reset = () => { setStep('pick'); setRes(null); setErr(null); onDone() }
  return (
    <div className="stack-s">
      {step === 'pick' && (
        <>
          <label className="small muted" htmlFor="tt">Pick a question that your team really has to answer</label>
          <select id="tt" value={task} onChange={(e) => setTask(e.target.value)}><option value="">Choose…</option>{starters.map((s) => <option key={s}>{s}</option>)}</select>
          <div><button className="btn" disabled={!task} onClick={() => start('manual')}>Start the clock: I will look it up myself</button></div>
        </>
      )}
      {step === 'manual' && (
        <>
          <p className="q">{task}</p>
          <p>Search the old way (GitHub, Jira, Slack). <Stopwatch running /></p>
          <div className="row"><button className="btn" onClick={async () => { await save('manual', true); setStep('ask') }}>I found it</button>
            <button className="btn quiet" onClick={async () => { await save('manual', false); setStep('ask') }}>I gave up</button></div>
        </>
      )}
      {step === 'ask' && (
        <>
          <p className="q">{task}</p>
          <p className="muted">Your manual time is saved. Now the same question with Gitwhy.</p>
          <div><button className="btn" onClick={async () => { start('asking'); try { setRes(await api.ask(task, [])); setStep('judge') } catch (e) { setErr(e); setStep('judge') } }}>Start the clock: ask Gitwhy</button></div>
        </>
      )}
      {step === 'asking' && <Reading>Asking Gitwhy</Reading>}
      {step === 'judge' && (
        <>
          {res?.headline && <p className="headline"><Hl text={res.headline.text} k={res.headline.key} /></p>}
          {res && !res.headline && <p className="notice">{res.status === 'insufficient' ? 'No source backs an answer.' : 'No headline came back.'}</p>}
          <p>Read the answer and its sources, then say whether it gave you what you needed.</p>
          <div className="row"><button className="btn" onClick={async () => { await save('gitwhy', true); reset() }}>It answered the question</button>
            <button className="btn quiet" onClick={async () => { await save('gitwhy', false); reset() }}>It did not</button></div>
        </>
      )}
      {err && <Problem error={err} />}
    </div>
  )
}

export default function Results() {
  const [assume, setAssume] = useState('')
  const [n, setN] = useState(0)
  const starters = useAsync(api.starters)
  const r = useAsync(() => api.results(assume), [assume, n])
  const d = r.data
  const t = d?.timed
  return (
    <div className="stack">
      <div><h1>What it has done for this team, measured.</h1>
        <p className="lede">Counted from real use and from timed tasks. Figures from people's ratings and figures from assumptions are kept apart and labelled.</p></div>
      {r.error && <Problem error={r.error} />}
      {d && (
        <>
          <section className="sect"><h2>Measured</h2>
            <table className="tbl"><tbody>
              <tr><td>Questions answered with sources</td><td className="num" style={{ whiteSpace: 'nowrap' }}>{d.measured.questions_answered} of {d.measured.questions_asked}</td></tr>
              <tr><td>Median time to a sourced answer, all questions</td><td className="num">{fmt(d.measured.median_seconds_to_sourced_answer)}</td></tr>
              <tr><td>Median time to a sourced answer, first-time questions ({d.measured.first_time_questions})</td><td className="num">{fmt(d.measured.median_seconds_first_time_question)}</td></tr>
              <tr><td>Pull requests checked against earlier decisions</td><td className="num">{d.measured.prs_reviewed}</td></tr>
              <tr><td>Repeated issues detected (an earlier decision or reviewer comment a PR runs against)</td><td className="num">{d.measured.repeated_issues_detected}</td></tr>
              <tr><td>Statements shown / removed because no source backs them</td><td className="num">{d.measured.citations.statements_shown} / {d.measured.citations.statements_removed_by_guard}</td></tr>
              <tr><td>Plans, handover briefs, impact checks, departure briefs</td><td className="num">{Object.values(d.measured.other).join(' · ')}</td></tr>
            </tbody></table>
            <p className="small muted">“Detected” is not “prevented”: it counts warnings shown, not mistakes that would have shipped.</p></section>
          <section className="sect"><h2>Rated by people</h2>
            <table className="tbl"><tbody>
              <tr><td>Answers rated</td><td className="num">{d.rated_by_people.ratings}</td></tr>
              <tr><td>Rated correct (of those with a verdict)</td><td className="num">{d.rated_by_people.correct_share == null ? 'no ratings yet' : `${Math.round(d.rated_by_people.correct_share * 100)}% (${d.rated_by_people.answers_correct} of ${d.rated_by_people.answers_correct + d.rated_by_people.answers_incorrect})`}</td></tr>
              <tr><td>Question resolved</td><td className="num">{d.rated_by_people.resolved}</td></tr>
              <tr><td>Onboarding questions resolved</td><td className="num">{d.rated_by_people.onboarding_questions_resolved}</td></tr>
            </tbody></table>
            <p className="small muted">Rate an answer with the buttons under it on the Ask page.</p></section>
          <section className="sect"><h2>Time to find a decision: by hand against Gitwhy</h2>
            {t.comparison
              ? <p className="headline">Median {fmt(t.comparison.median_manual_s)} by hand, {fmt(t.comparison.median_gitwhy_s)} with Gitwhy, over {t.comparison.paired_tasks} questions timed both ways. Faster with Gitwhy in {t.comparison.faster_in} of {t.comparison.of}.</p>
              : <p className="notice">No comparison yet. {t.paired_tasks} of {t.needed_pairs} questions have been timed both ways, and no time saving is claimed until there are {t.needed_pairs}.</p>}
            <p className="small muted">{t.timed_tasks} timings recorded{t.not_found ? `, ${t.not_found} where the answer was not found (left out of the medians)` : ''}. By hand so far: {fmt(t.manual_median_s)}. With Gitwhy: {fmt(t.gitwhy_median_s)}.</p>
            <TimedTask starters={starters.data || []} onDone={() => setN((x) => x + 1)} /></section>
          <section className="sect"><h2>Estimate</h2>
            <p className="muted">This is arithmetic on a number you type, not a result.</p>
            <label className="small muted" htmlFor="as">Minutes you think one sourced answer saves</label>
            <input id="as" type="number" min="0" max="600" value={assume} onChange={(e) => setAssume(e.target.value)} style={{ maxWidth: 120 }} />
            {d.estimate && <p className="notice"><b>{d.estimate.label}:</b> about {d.estimate.hours} hours, from {d.estimate.based_on} ({d.estimate.assumed_minutes_saved_per_answer} min each).</p>}</section>
        </>
      )}
    </div>
  )
}
