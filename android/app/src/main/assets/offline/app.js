// Офлайн-экран: данные из облачного снимка + очередь команд. Работает внутри приложения (мост window.HomeHubApp).
(function () {
  'use strict'
  var bridge = window.HomeHubApp || {}
  var view = 'days', person = null, listId = null, sel = null, scope = 'series'
  var snap = null, pending = [], lastKey = ''

  function h(tag, props, kids) {
    var el = document.createElement(tag)
    for (var k in props || {}) {
      var v = props[k]
      if (k === 'class') el.className = v
      else if (k === 'text') el.textContent = v
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v)
      else if (k === 'style') el.setAttribute('style', v)
      else if (v !== false && v != null) el.setAttribute(k, v)
    }
    ;[].concat(kids || []).forEach(function (c) { if (c != null && c !== false) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c) })
    return el
  }
  function parse(s, d) { try { return JSON.parse(s) } catch (e) { return d } }
  function read() {
    snap = parse(bridge.getSnapshot && bridge.getSnapshot(), null)
    pending = parse(bridge.getPending && bridge.getPending(), [])
  }
  function applied(id) { return snap && (snap.applied || []).indexOf(id) >= 0 }
  function live() { return pending.filter(function (o) { return !applied(o.id) }) }

  // --- снимок + ещё не подтверждённые серверов команды (чтобы изменения были видны сразу) ---
  function overlay() {
    var s = JSON.parse(JSON.stringify(snap))
    live().forEach(function (o) {
      if (o.type === 'escort') {
        s.events.forEach(function (e) {
          if (e.uid !== o.uid || e.duty || !e.escort) return
          if (o.occurrence && e.start !== o.occurrence) return
          if (o.role === 'mode') { if (o.person) e.escort.mode = o.person }
          else if (o.role === 'dropoff' || o.role === 'pickup') {
            var r = e.escort[o.role]
            r.skip = o.person === '-'
            r.person = o.person && o.person !== '-' ? o.person : null
            r.conflicts = []
            e.escort_issue = null
          }
          e._pending = true
        })
      } else if (o.type === 'item_add') {
        s.lists.forEach(function (l) { if (l.id === o.list_id) l.items.push({ id: 'p:' + o.id, text: o.text, done: false, _pending: true }) })
      } else if (o.type === 'item_done') {
        s.lists.forEach(function (l) { l.items.forEach(function (i) { if (i.id === o.item_id) { i.done = !!o.done; i._pending = true } }) })
      } else if (o.type === 'item_delete') {
        s.lists.forEach(function (l) { l.items = l.items.filter(function (i) { return i.id !== o.item_id }) })
      }
    })
    return s
  }
  function queue(op) {
    if (bridge.queueOp) bridge.queueOp(JSON.stringify(op))
    read(); render()
  }

  var P = function (s, id) { return (s.people || []).filter(function (p) { return p.id === id })[0] }
  var pname = function (s, id) { var p = P(s, id); return p ? p.name : id }
  var hm = function (iso) { return iso.slice(11, 16) }
  var DAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
  var MON = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
  function localDate(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2) }
  function dayLabel(date) {
    var t = new Date(), today = localDate(t)
    var tm = new Date(t.getTime() + 864e5), tomorrow = localDate(tm)
    var d = new Date(date + 'T12:00:00')
    var base = DAYS[d.getDay()] + ', ' + d.getDate() + ' ' + MON[d.getMonth()]
    base = base.charAt(0).toUpperCase() + base.slice(1)
    return date === today ? 'Сегодня · ' + base : date === tomorrow ? 'Завтра · ' + base : base
  }

  var syncing = 0
  function syncText() {
    var st = {}
    try { st = JSON.parse(bridge.syncStatus ? bridge.syncStatus() : '{}') } catch (e) {}
    if (syncing && Date.now() - syncing < 3500) return 'Обновляю…'
    if (st.error) return 'Не обновилось: ' + st.error
    if (snap && !snap.events) return 'Облачный снимок старого формата — сервер дома ещё не записал новый. Попробуйте позже.'
    return ''
  }
  function banner() {
    var b = document.getElementById('banner')
    b.textContent = ''
    var gen = snap && snap.generated ? snap.generated.slice(8, 10) + '.' + snap.generated.slice(5, 7) + ' ' + hm(snap.generated) : '—'
    var n = live().length
    b.appendChild(h('span', {}, [h('b', { text: 'Вне дома' }), ' · данные на ' + gen + (n ? ' · ждут отправки: ' + n : '')]))
    b.appendChild(h('button', { text: 'Обновить', onclick: function () {
      if (!bridge.syncNow) return
      bridge.syncNow(); syncing = Date.now(); banner(); setTimeout(banner, 4000); setTimeout(banner, 10000)
    } }))
    var st = syncText()
    if (st) b.appendChild(h('div', { class: 'sync', text: st }))
    b.appendChild(h('button', { text: 'Домой', onclick: function () { bridge.retryHome && bridge.retryHome() } }))
  }

  // --- События ---
  function escBadge(s, e) {
    if (!e.escort) return null
    var x = e.escort
    if (x.mode === 'home') return h('span', { class: 'tag', text: 'дома' })
    if (x.mode === 'together') return h('span', { class: 'tag', text: 'все вместе' })
    var parts = []
    ;[['dropoff', '→'], ['pickup', '←']].forEach(function (r) {
      var v = x[r[0]]
      if (v.skip) return
      parts.push(r[1] + ' ' + (v.person ? pname(s, v.person) : 'кто?'))
    })
    var bad = e.escort_issue === 'conflict', warn = e.escort_issue === 'unassigned'
    return h('span', { class: 'tag' + (bad ? ' bad' : warn ? ' warn' : ''), text: parts.join('  ') })
  }
  function daysView(s) {
    var root = h('div')
    root.appendChild(h('h1', { text: 'События' }))
    var qin = h('input', { placeholder: 'Быстро: Врач завтра в 18:00 Марку', 'aria-label': 'Новое событие', autocomplete: 'off' })
    root.appendChild(h('form', { class: 'add', onsubmit: function (ev) {
      ev.preventDefault()
      var t = qin.value.trim()
      if (!t) return
      queue({ type: 'event_quick', text: t })
    } }, [qin, h('button', { text: 'Добавить' })]))
    var queued = live().filter(function (o) { return o.type === 'event_quick' })
    if (queued.length) root.appendChild(h('div', { class: 'group', style: 'margin-bottom:8px' }, queued.map(function (o) {
      return h('div', { class: 'row' }, [h('span', { class: 'main s', text: o.text }), h('span', { class: 'tag pend', text: 'отправляется' })])
    })))
    var chips = h('div', { class: 'chips', style: 'margin:6px 12px' }, [
      h('button', { class: 'chip' + (!person ? ' on' : ''), text: 'Все', onclick: function () { person = null; render() } })
    ].concat((s.people || []).map(function (p) {
      return h('button', { class: 'chip' + (person === p.id ? ' on' : ''), style: '--c:' + p.color, text: (p.emoji || '') + ' ' + p.name,
        onclick: function () { person = p.id; render() } })
    })))
    root.appendChild(chips)
    var evs = s.events.filter(function (e) { return person ? e.people.indexOf(person) >= 0 : !e.duty })
    var byDay = {}
    evs.forEach(function (e) { (byDay[e.start.slice(0, 10)] = byDay[e.start.slice(0, 10)] || []).push(e) })
    var keys = Object.keys(byDay).sort()
    if (!keys.length) root.appendChild(h('p', { class: 'empty', text: 'Событий нет' }))
    var today = localDate(new Date())
    keys.forEach(function (k) {
      root.appendChild(h('h2', { class: k === today ? 'today' : '', text: dayLabel(k) }))
      root.appendChild(h('div', { class: 'group' }, byDay[k].sort(function (a, b) { return a.start < b.start ? -1 : 1 }).map(function (e) {
        var p = P(s, e.people[0])
        var past = !e.all_day && new Date(e.end) < new Date()
        return h('button', { class: 'row', style: past ? 'opacity:.5' : '', onclick: function () { sel = e.duty ? e.duty.parent : e.id; scope = 'series'; render() } }, [
          h('span', { class: 'bar', style: 'background:' + (e.color || (p ? p.color : '#888')) }),
          h('span', { class: 'when', text: e.all_day ? 'весь день' : hm(e.start) + '\n' + hm(e.end) }),
          h('span', { class: 'main' }, [
            h('div', { class: 't', text: e.title }),
            h('div', { class: 's', text: (e.location ? e.location + ' · ' : '') + e.people.map(function (id) { return pname(s, id) }).join(', ') }),
            escBadge(s, e), e._pending ? h('span', { class: 'tag pend', text: 'отправляется' }) : null
          ])
        ])
      })))
    })
    root.appendChild(h('p', { class: 'note', text: 'Это снимок из облака, новые события появятся в календаре через минуту-две после отправки, а менять и удалять их можно только дома. Назначения поездок и списки можно менять — изменения дойдут до дома в течение минуты.' }))
    return root
  }

  function sheet(s) {
    var bg = document.getElementById('sheet-bg'), box = document.getElementById('sheet')
    if (!sel) { bg.classList.remove('open'); return }
    var e = s.events.filter(function (x) { return x.id === sel })[0]
    if (!e) { sel = null; bg.classList.remove('open'); return }
    bg.classList.add('open')
    box.textContent = ''
    box.appendChild(h('button', { class: 'close', text: 'Готово', onclick: function () { sel = null; render() } }))
    box.appendChild(h('h3', { text: e.title }))
    box.appendChild(h('p', { class: 'sub', text: dayLabel(e.start.slice(0, 10)) + (e.all_day ? ', весь день' : ', ' + hm(e.start) + '–' + hm(e.end)) + (e.location ? ' · ' + e.location : '') }))
    if (!e.escort) { box.appendChild(h('p', { class: 'sub', text: 'У этого события нет поездок. Менять его можно только дома.' })); return }
    var x = e.escort
    var op = function (role, p) { queue({ type: 'escort', uid: e.uid, occurrence: scope === 'once' && e.recurring ? e.start : null, role: role, person: p }) }
    if (e.recurring) box.appendChild(h('div', { class: 'seg', style: 'margin:6px 0' }, [
      h('button', { class: scope === 'series' ? 'on' : '', text: 'Всегда', onclick: function () { scope = 'series'; render() } }),
      h('button', { class: scope === 'once' ? 'on' : '', text: 'Только ' + e.start.slice(8, 10) + '.' + e.start.slice(5, 7), onclick: function () { scope = 'once'; render() } })
    ]))
    box.appendChild(h('div', { class: 'seg', style: 'margin:10px 0' }, [['escort', 'Отвозят'], ['together', 'Все вместе'], ['home', 'Дома']].map(function (m) {
      return h('button', { class: x.mode === m[0] ? 'on' : '', text: m[1], onclick: function () { op('mode', m[0]) } })
    })))
    if (x.mode === 'escort') {
      var adults = (s.people || []).filter(function (p) { return !p.needs_escort })
      ;[['dropoff', 'Отвезти'], ['pickup', 'Забрать']].forEach(function (r) {
        var v = x[r[0]]
        box.appendChild(h('div', { class: 'label' }, [r[1], h('small', { text: hm(v.window[0]) + '–' + hm(v.window[1]) })]))
        box.appendChild(h('div', { class: 'chips' }, adults.map(function (p) {
          return h('button', { class: 'chip' + (v.person === p.id ? ' on' : ''), style: '--c:' + p.color, text: (p.emoji || '') + ' ' + p.name, onclick: function () { op(r[0], p.id) } })
        }).concat([h('button', { class: 'chip' + (v.skip ? ' on' : ''), text: 'Не нужно', onclick: function () { op(r[0], '-') } })])))
        if (v.conflicts && v.conflicts.length) box.appendChild(h('p', { class: 'bad-t', text: 'В это время занят(а): ' + v.conflicts.map(function (c) { return c.title }).join(', ') + ' (по данным снимка)' }))
        else if (!v.person && !v.skip) box.appendChild(h('p', { class: 'warn-t', text: 'Никто не назначен' }))
      })
      box.appendChild(h('div', { class: 'label' }, ['В пути', h('small', { text: x.travel && x.travel.minutes != null ? x.travel.minutes + ' мин' : 'как в настройках' })]))
      box.appendChild(h('div', { class: 'chips' }, [h('button', { class: 'chip', text: 'Как в настройках', onclick: function () { op('travel', null) } })]
        .concat([5, 10, 15, 20, 30, 45, 60].map(function (m) { return h('button', { class: 'chip', text: m + ' мин', onclick: function () { op('travel', String(m)) } }) }))))
    }
    if (e._pending) box.appendChild(h('p', { class: 'note', text: 'Изменение отправляется домой…' }))
  }

  // --- Списки ---
  function listsView(s) {
    var root = h('div')
    root.appendChild(h('h1', { text: 'Списки' }))
    if (!s.lists || !s.lists.length) { root.appendChild(h('p', { class: 'empty', text: 'Списков нет' })); return root }
    if (!listId || !s.lists.filter(function (l) { return l.id === listId }).length) listId = s.lists[0].id
    root.appendChild(h('div', { class: 'seg lists-tabs' }, s.lists.map(function (l) {
      return h('button', { class: l.id === listId ? 'on' : '', text: l.name, onclick: function () { listId = l.id; render() } })
    })))
    var l = s.lists.filter(function (x) { return x.id === listId })[0]
    var input = h('input', { placeholder: 'Что добавить?', 'aria-label': 'Новая запись', autocomplete: 'off' })
    root.appendChild(h('form', { class: 'add', onsubmit: function (ev) {
      ev.preventDefault()
      var t = input.value.trim()
      if (!t) return
      queue({ type: 'item_add', list_id: l.id, text: t })
    } }, [input, h('button', { text: 'Добавить' })]))
    if (!l.items.length) root.appendChild(h('p', { class: 'empty', text: 'Список пуст' }))
    else root.appendChild(h('div', { class: 'group' }, l.items.map(function (i) {
      var real = typeof i.id === 'number'
      return h('div', { class: 'row' + (i.done ? ' done' : '') }, [
        h('button', { class: 'check', disabled: !real, 'aria-label': 'Отметить', onclick: function () { queue({ type: 'item_done', item_id: i.id, done: !i.done }) } },
          i.done ? [document.createTextNode('✓')] : []),
        h('span', { class: 'txt main', text: i.text }),
        i._pending ? h('span', { class: 'tag pend', text: real ? '…' : 'отправляется' }) : null,
        real ? h('button', { style: 'border:0;background:none;color:var(--ink3);font-size:22px', text: '×', 'aria-label': 'Удалить',
          onclick: function () { queue({ type: 'item_delete', item_id: i.id }) } }) : null
      ])
    })))
    return root
  }

  function render() {
    var v = document.getElementById('view')
    document.getElementById('tab-days').className = view === 'days' ? 'on' : ''
    document.getElementById('tab-lists').className = view === 'lists' ? 'on' : ''
    if (!snap || !snap.events) { v.textContent = ''; v.appendChild(h('p', { class: 'empty', text: 'Облачного снимка пока нет. Подключитесь к домашней сети.' })); banner(); return }
    var s = overlay()
    banner()
    var scrollY = window.scrollY
    v.textContent = ''
    v.appendChild(view === 'days' ? daysView(s) : listsView(s))
    sheet(s)
    window.scrollTo(0, scrollY)
  }

  document.getElementById('tab-days').onclick = function () { view = 'days'; render() }
  document.getElementById('tab-lists').onclick = function () { view = 'lists'; render() }
  document.getElementById('sheet-bg').addEventListener('click', function (ev) { if (ev.target === this) { sel = null; render() } })

  // Данные обновляются в фоне (Sync): перерисовываем, когда снимок или очередь изменились.
  function poll() {
    var a = bridge.getSnapshot ? bridge.getSnapshot() : '', b = bridge.getPending ? bridge.getPending() : ''
    var key = a.length + ':' + (snap && snap.generated) + ':' + b
    if (key !== lastKey && !(document.activeElement && document.activeElement.tagName === 'INPUT')) { lastKey = key; read(); render() }
  }
  read(); render(); lastKey = (bridge.getSnapshot ? bridge.getSnapshot().length : 0) + ':' + (snap && snap.generated) + ':' + (bridge.getPending ? bridge.getPending() : '')
  setInterval(poll, 5000)
})()
