import { useEffect, useState, useCallback } from 'react'

export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const run = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    return fn().then(
      (data) => setState({ loading: false, data, error: null }),
      (error) => setState({ loading: false, data: null, error }),
    )
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { ...state, reload: run }
}

export function Async({ state, empty, children }) {
  if (state.loading && !state.data) return <div className="state" role="status">Loading…</div>
  if (state.error) {
    return (
      <div className="state error" role="alert">
        <strong>Something went wrong.</strong> {state.error.message}
        {state.reload && <button onClick={state.reload}>Retry</button>}
      </div>
    )
  }
  const d = state.data
  if (empty && (!d || (Array.isArray(d) && d.length === 0))) return <div className="state">{empty}</div>
  return children(d)
}

const LABEL_HELP = {
  verified: 'Supported by structural or explicit source evidence',
  inferred: 'Derived or unconfirmed; treat as a hypothesis',
  proposed: 'Suggested design or action; needs human approval',
}
export function Badge({ kind }) {
  return <span className={`badge ${kind}`} title={LABEL_HELP[kind] || kind}>{kind}</span>
}
export const Chip = ({ children, onClick, active }) => (
  <button className={`chip ${active ? 'active' : ''}`} onClick={onClick}>{children}</button>
)
export const Card = ({ title, right, children }) => (
  <section className="card">
    {(title || right) && <header><h3>{title}</h3>{right}</header>}
    {children}
  </section>
)
export const fmt = (iso) => (iso ? new Date(iso).toISOString().slice(0, 16).replace('T', ' ') : '—')
