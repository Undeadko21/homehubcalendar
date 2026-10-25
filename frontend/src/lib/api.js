// Тонкая обёртка над HTTP API бэкенда.
async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  })
  if (res.status === 401) {
    const err = new Error('auth_required')
    err.auth = true
    throw err
  }
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}

const q = (params) => new URLSearchParams(params).toString()

export const api = {
  config: () => request('GET', '/api/config'),
  events: (start, end) => request('GET', `/api/events?${q({ start, end })}`),
  holidays: (start, end) => request('GET', `/api/holidays?${q({ start, end })}`),
  status: () => request('GET', '/api/status'),
  sync: () => request('POST', '/api/sync'),
  login: (pin) => request('POST', '/api/login', { pin }),
  savePerson: (p) => request('PUT', `/api/people/${encodeURIComponent(p.id)}`, p),
  deletePerson: (id) => request('DELETE', `/api/people/${encodeURIComponent(id)}`),
  saveAccount: (id, username, password) => request('PUT', `/api/accounts/${encodeURIComponent(id)}`, { username, password }),
  patchCalendar: (key, patch) => request('PATCH', `/api/calendars/${key}`, patch),
}
