import { useState } from 'react'
import product from '@product'
import { api, setSession } from '../api.js'
import { LogoMark } from '../ui.jsx'

export const TEST_ACCOUNT = { email: 'demo@gitwhy.test', password: 'gitwhy-demo-2026' }

export default function Welcome({ onSignedIn }) {
  const [mode, setMode] = useState('signup')
  const [f, setF] = useState({ name: '', email: '', password: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e, creds) => {
    e?.preventDefault(); setBusy(true); setErr(null)
    try {
      const body = creds || f
      const r = mode === 'signup' && !creds ? await api.signup(body) : await api.login({ email: body.email, password: body.password })
      setSession(r.token); onSignedIn(r)
    } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <main className="welcome">
      <div className="welcome-in stack">
        <div className="brand"><LogoMark /><b>{product.name}</b></div>
        <div>
          <h1>{mode === 'signup' ? 'Know why your code is the way it is.' : 'Welcome back.'}</h1>
          <p className="lede">{mode === 'signup'
            ? 'Connect GitHub and Jira. Gitwhy reads the pull requests, review threads, tickets and commits, then answers with the exact words of the people who wrote them.'
            : 'Sign in to your organizations.'}</p>
        </div>
        <form className="stack-s" onSubmit={submit}>
          {mode === 'signup' && <><label className="sr" htmlFor="nm">Your name</label><input id="nm" type="text" placeholder="Your name" value={f.name} onChange={set('name')} autoComplete="name" /></>}
          <label className="sr" htmlFor="em">Email</label><input id="em" type="text" placeholder="Work email" value={f.email} onChange={set('email')} autoComplete="email" />
          <label className="sr" htmlFor="pw">Password</label><input id="pw" type="password" placeholder={mode === 'signup' ? 'Password, at least 8 characters' : 'Password'} value={f.password} onChange={set('password')} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />
          {err && <p className="notice err" role="alert">{err}</p>}
          <div className="row"><button className="btn" type="submit" disabled={busy || !f.email || f.password.length < 8}>{mode === 'signup' ? 'Create account' : 'Sign in'}</button>
            <button type="button" className="btn quiet" onClick={() => { setMode(mode === 'signup' ? 'login' : 'signup'); setErr(null) }}>{mode === 'signup' ? 'I have an account' : 'Create an account'}</button></div>
        </form>
        <div className="notice">
          <b style={{ fontWeight: 600 }}>Just looking around?</b> A test organization with sample data is ready.
          <div className="small muted" style={{ margin: '4px 0 12px' }}>Test account: <code>{TEST_ACCOUNT.email}</code> · <code>{TEST_ACCOUNT.password}</code></div>
          <button className="btn quiet small" disabled={busy} onClick={(e) => { setMode('login'); submit(e, TEST_ACCOUNT) }}>Open the test organization</button>
        </div>
      </div>
    </main>
  )
}
