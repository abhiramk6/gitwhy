const TOKEN_KEY = 'lore_demo_token'

export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' } }
export const setToken = (t) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } }

async function request(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  const token = getToken()
  if (token) headers['X-Demo-Token'] = token
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
  overview: () => request('/api/overview'),
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
