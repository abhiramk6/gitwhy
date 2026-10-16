const TOKEN_KEY = 'gitwhy_demo_token'

export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' } }
export const setToken = (t) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } }

const SESSION_KEY = 'gitwhy_session'
const ORG_KEY = 'gitwhy_org'
export const getSession = () => { try { return localStorage.getItem(SESSION_KEY) || '' } catch { return '' } }
export const setSession = (t) => { try { t ? localStorage.setItem(SESSION_KEY, t) : localStorage.removeItem(SESSION_KEY) } catch { /* private mode */ } }
export const getOrg = () => { try { return localStorage.getItem(ORG_KEY) || '' } catch { return '' } }
export const setOrg = (o) => { try { o ? localStorage.setItem(ORG_KEY, o) : localStorage.removeItem(ORG_KEY) } catch { /* private mode */ } }

async function request(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  const token = getToken()
  if (token) headers['X-Demo-Token'] = token
  const session = getSession()
  if (session) headers.Authorization = `Bearer ${session}`
  const org = getOrg()
  if (org) headers['X-Org'] = org
  const res = await fetch(path, { ...opts, headers })
  if (!res.ok) {
    let detail = res.statusText
    try { const j = await res.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* ignore */ }
    const err = new Error(detail || `HTTP ${res.status}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  meta: () => request('/api/meta'),
  signup: (b) => request('/api/auth/signup', { method: 'POST', body: JSON.stringify(b) }),
  login: (b) => request('/api/auth/login', { method: 'POST', body: JSON.stringify(b) }),
  me: () => request('/api/auth/me'),
  createOrg: (name) => request('/api/orgs', { method: 'POST', body: JSON.stringify({ name }) }),
  testGithub: (token, owner) => request('/api/connections/github/test', { method: 'POST', body: JSON.stringify({ token, owner }) }),
  testJira: (site, email, token) => request('/api/connections/jira/test', { method: 'POST', body: JSON.stringify({ site, email, token }) }),
  saveConnections: (slug, b) => request(`/api/orgs/${slug}/connections`, { method: 'PUT', body: JSON.stringify(b) }),
  startSync: (slug) => request(`/api/orgs/${slug}/sync`, { method: 'POST' }),
  syncStatus: (slug) => request(`/api/orgs/${slug}/sync`),
  overview: () => request('/api/overview'),
  sources: () => request('/api/sources'),
  ingestion: () => request('/api/ingestion'),
  starters: () => request('/api/starters'),
  ask: (question, history) => request('/api/ask', { method: 'POST', body: JSON.stringify({ question, history }) }),
  impact: (question) => request('/api/impact', { method: 'POST', body: JSON.stringify({ question }) }),
  feedback: (b) => request('/api/feedback', { method: 'POST', body: JSON.stringify(b) }),
  timedTask: (b) => request('/api/timed-tasks', { method: 'POST', body: JSON.stringify(b) }),
  results: (assume) => request('/api/results' + (assume ? `?assumed_minutes=${encodeURIComponent(assume)}` : '')),
  tags: (ids) => request('/api/tags?ids=' + encodeURIComponent(ids.join(','))),
  provenance: (rid) => request(`/api/provenance/${rid}`),
  prs: () => request('/api/prs?limit=80'),
  reviewPr: (repo, n) => request(`/api/prs/${encodeURIComponent(repo)}/${n}/review`, { method: 'POST' }),
  guidance: () => request('/api/memory/guidance'),
  timeline: (id) => request(`/api/memory/guidance/${id}/timeline`, { method: 'POST' }),
  people: () => request('/api/people'),
  person: (login) => request(`/api/people/${encodeURIComponent(login)}`),
  handover: (login) => request(`/api/people/${encodeURIComponent(login)}/handover`, { method: 'POST' }),
  files: () => request('/api/files'),
  explainTrace: (repo, path) => request(`/api/archaeology/explain?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`, { method: 'POST' }),
  trace: (repo, path) => request(`/api/archaeology?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`),
  graph: () => request('/api/graph'),
  entity: (id) => request(`/api/entities/${id}`),
  search: (q) => request(`/api/search?q=${encodeURIComponent(q)}&k=8`),
  knowledge: (params = {}) => request('/api/knowledge?' + new URLSearchParams(params)),
  setFactStatus: (id, status) => request(`/api/knowledge/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
  remember: (body) => request('/api/memory/remember', { method: 'POST', body: JSON.stringify(body) }),
  override: (body) => request('/api/memory/override', { method: 'POST', body: JSON.stringify(body) }),
  plans: () => request('/api/plans'),
  plan: (id) => request(`/api/plans/${id}`),
  createPlan: (request_) => request('/api/plans', { method: 'POST', body: JSON.stringify({ request: request_ }) }),
  setPlanStatus: (id, status) => request(`/api/plans/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
}
