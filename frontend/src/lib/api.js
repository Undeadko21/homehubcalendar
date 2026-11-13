// Тонкая обёртка над HTTP API бэкенда.
// Метка этого экрана: сервер сообщает по SSE, кто сделал изменение, и мы не перезагружаемся по собственной записи.
export const CLIENT_ID = Math.random().toString(36).slice(2, 12)

// Вызывается, когда любой запрос получил 401 (сессия кончилась или пароль ещё не введён): приложение покажет экран входа.
let onAuth = null
export function setAuthHandler(fn) { onAuth = fn }

// Состояние связи с сервером: экран показывает спокойную полосу «Нет связи с домом» вместо технической ошибки.
import { reactive } from 'vue'
export const net = reactive({ offline: false, since: null, lastOk: null, server: false })

function markOk() { net.offline = false; net.server = false; net.since = null; net.lastOk = Date.now() }
function markDown(server) {
  if (!net.offline) net.since = Date.now()
  net.offline = true
  net.server = !!server
}

async function request(method, url, body) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-Client-Id'] = CLIENT_ID
  let res
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    })
  } catch (e) {
    markDown(false)
    const err = new Error('Нет связи с сервером')
    err.offline = true
    throw err
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    markDown(true)
    const err = new Error('Сервер дома не отвечает')
    err.offline = true
    throw err
  }
  markOk()
  if (res.status === 401) {
    const err = new Error('auth_required')
    err.auth = true
    if (onAuth && !url.endsWith('/api/login')) onAuth()
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
  feeds: () => request('GET', '/api/feeds'),
  saveFeed: (b) => request('PUT', '/api/feeds', b),
  deleteFeed: (id) => request('DELETE', `/api/feeds/${encodeURIComponent(id)}`),
  createEvent: (b) => request('POST', '/api/event', b),
  updateEvent: (uid, b) => request('PUT', `/api/event/${encodeURIComponent(uid)}`, b),
  deleteEvent: (uid, calendar, occurrence) =>
    request('DELETE', `/api/event/${encodeURIComponent(uid)}?${q(occurrence ? { calendar, occurrence } : { calendar })}`),
  importSettings: (blob) => request('POST', '/api/import', blob),
  selftestWrite: (calendar) => request('POST', '/api/selftest/write', { calendar }),
  createSection: (b) => request('POST', '/api/section', b),
  conflicts: (b) => request('POST', '/api/conflicts', b),
  backupFiles: () => request('GET', '/api/backup/files'),
  backupVerify: (name) => request('POST', '/api/backup/verify', { name: name || null }),
  backupDrill: () => request('POST', '/api/backup/drill'),
  backupRestore: (name) => request('POST', '/api/backup/restore', { name }),
  person: (id) => request('GET', `/api/person/${encodeURIComponent(id)}`),
  runChecks: () => request('POST', '/api/checks'),
  perf: () => request('GET', '/api/perf'),
  quick: (text) => request('POST', '/api/quick', { text }),
  changes: () => request('GET', '/api/changes'),
  undoChange: (id) => request('POST', `/api/changes/${id}/undo`),
  flushChanges: () => request('POST', '/api/changes/flush'),
  setEventColor: (uid, color) => request('POST', '/api/event-color', { uid, color }),
  setEventStar: (uid, star) => request('POST', '/api/event-star', { uid, star }),
  countdowns: () => request('GET', '/api/countdowns'),
  shops: () => request('GET', '/api/shops'),
  setSharedColor: (color) => request('PUT', '/api/settings/shared-color', { color }),
  setEventPeople: (uid, people) => request('POST', '/api/event-people', { uid, people }),
  setEscort: (uid, occurrence, role, person) => request('POST', '/api/escort', { uid, occurrence, role, person }),
  saveEscortSettings: (s) => request('PUT', '/api/settings/escort', s),
  access: () => request('GET', '/api/access'),
  putAccess: (body) => request('PUT', '/api/access', body),
  rotateAccess: (which) => request('POST', `/api/access/rotate/${which}`),
  ntfyTest: () => request('POST', '/api/access/ntfy-test'),
  probeAccess: () => request('POST', '/api/access/probe'),
  sessions: () => request('GET', '/api/sessions'),
  revokeSession: (id) => request('DELETE', `/api/sessions/${id}`),
  revokeAll: (keepCurrent) => request('POST', '/api/sessions/revoke-all', { keep_current: keepCurrent }),
  loginQr: () => request('POST', '/api/login/qr'),
  free: (params) => request('GET', `/api/free?${q(params)}`),
  appInfo: () => request('GET', '/api/app'),
  templateSuggestions: () => request('GET', '/api/templates/suggestions'),
  templates: () => request('GET', '/api/templates'),
  saveTemplate: (t) => request('PUT', '/api/templates', t),
  deleteTemplate: (id) => request('DELETE', `/api/templates/${id}`),
  birthdays: (days = 60) => request('GET', `/api/birthdays?days=${days}`),
  saveBirthday: (b) => request('PUT', '/api/birthdays', b),
  deleteBirthday: (id) => request('DELETE', `/api/birthdays/${id}`),
  search: (params) => request('GET', `/api/search?${q(params)}`),
  eventFiles: (uid) => request('GET', `/api/event-files?${q({ uid })}`),
  addEventLink: (uid, url, name) => request('POST', '/api/event-files/link', { uid, url, name: name || '' }),
  deleteEventFile: (id) => request('DELETE', `/api/event-files/${id}`),
  uploadEventFile: async (uid, file) => {
    const res = await fetch(`/api/event-files/upload?${q({ uid, name: file.name })}`, {
      method: 'POST', body: file, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/octet-stream', 'X-Client-Id': CLIENT_ID },
    })
    if (!res.ok) {
      let detail = res.statusText
      try { detail = (await res.json()).detail || detail } catch {}
      throw new Error(detail)
    }
    return res.json()
  },
  route: (location) => request('POST', '/api/route', { location }),
  lists: () => request('GET', '/api/lists'),
  addList: (name) => request('POST', '/api/lists', { name }),
  renameList: (id, name) => request('PUT', `/api/lists/${id}`, { name }),
  deleteList: (id) => request('DELETE', `/api/lists/${id}`),
  addItem: (id, text, person_id = null, due = null) => request('POST', `/api/lists/${id}/items`, { text, person_id, due }),
  patchItem: (id, patch) => request('PATCH', `/api/items/${id}`, patch),
  deleteItem: (id) => request('DELETE', `/api/items/${id}`),
  clearDone: (id) => request('POST', `/api/lists/${id}/clear-done`),
  cloud: () => request('GET', '/api/cloud'),
  saveCloud: (token) => request('PUT', '/api/cloud', { token }),
  pushCloud: () => request('POST', '/api/cloud/push'),
  saveCloudClient: (clientId) => request('PUT', '/api/cloud/client', { client_id: clientId }),
  domainCheck: (domain) => request('POST', '/api/access/domain-check', { domain }),
  eventReminders: () => request('GET', '/api/settings/event-reminders'),
  saveEventReminders: (people, extra) => request('PUT', '/api/settings/event-reminders', { people, ...(extra || {}) }),
  school: () => request('GET', '/api/school'),
  saveSchool: (breaks) => request('PUT', '/api/school', { breaks }),
  saveSchoolHide: (hide, hide_words) => request('PUT', '/api/school', { hide, hide_words }),
  stats: (start, end) => request('GET', `/api/stats?${q({ start, end })}`),
  system: () => request('GET', '/api/system'),
  forgetOps: (name) => request('POST', '/api/cloud/ops-forget', { name }),
  runBackup: () => request('POST', '/api/backup'),
  patchCalendar: (key, patch) => request('PATCH', `/api/calendars/${key}`, patch),
}
