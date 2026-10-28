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
  setEventPeople: (uid, people) => request('POST', '/api/event-people', { uid, people }),
  setEscort: (uid, occurrence, role, person) => request('POST', '/api/escort', { uid, occurrence, role, person }),
  saveEscortSettings: (s) => request('PUT', '/api/settings/escort', s),
  free: (params) => request('GET', `/api/free?${q(params)}`),
  appInfo: () => request('GET', '/api/app'),
  templates: () => request('GET', '/api/templates'),
  saveTemplate: (t) => request('PUT', '/api/templates', t),
  deleteTemplate: (id) => request('DELETE', `/api/templates/${id}`),
  birthdays: (days = 60) => request('GET', `/api/birthdays?days=${days}`),
  saveBirthday: (b) => request('PUT', '/api/birthdays', b),
  deleteBirthday: (id) => request('DELETE', `/api/birthdays/${id}`),
  search: (text) => request('GET', `/api/search?${q({ q: text })}`),
  lists: () => request('GET', '/api/lists'),
  addList: (name) => request('POST', '/api/lists', { name }),
  renameList: (id, name) => request('PUT', `/api/lists/${id}`, { name }),
  deleteList: (id) => request('DELETE', `/api/lists/${id}`),
  addItem: (id, text, person_id = null) => request('POST', `/api/lists/${id}/items`, { text, person_id }),
  patchItem: (id, patch) => request('PATCH', `/api/items/${id}`, patch),
  deleteItem: (id) => request('DELETE', `/api/items/${id}`),
  clearDone: (id) => request('POST', `/api/lists/${id}/clear-done`),
  cloud: () => request('GET', '/api/cloud'),
  saveCloud: (token) => request('PUT', '/api/cloud', { token }),
  pushCloud: () => request('POST', '/api/cloud/push'),
  school: () => request('GET', '/api/school'),
  saveSchool: (breaks) => request('PUT', '/api/school', { breaks }),
  stats: (start, end) => request('GET', `/api/stats?${q({ start, end })}`),
  system: () => request('GET', '/api/system'),
  runBackup: () => request('POST', '/api/backup'),
  patchCalendar: (key, patch) => request('PATCH', `/api/calendars/${key}`, patch),
}
