<template>
  <div>
    <div class="seg" role="tablist">
      <button v-for="p in PERIODS" :key="p.id" :class="{ on: period === p.id }" @click="period = p.id">{{ p.name }}</button>
    </div>
    <p class="group-note range">{{ rangeText }}</p>
    <p v-if="err" class="group-note err">{{ err }}</p>
    <template v-if="r">
      <div class="tiles">
        <div class="tile"><b>{{ r.events }}</b><span>{{ plural(r.events, 'встреча', 'встречи', 'встреч') }}</span></div>
        <div class="tile"><b>{{ r.hours }}</b><span>часов занято</span></div>
        <div class="tile"><b>{{ r.trips }}</b><span>{{ plural(r.trips, 'поездка', 'поездки', 'поездок') }}</span></div>
      </div>

      <h3 class="group-title">По людям</h3>
      <div class="group">
        <div v-for="p in r.people" :key="p.id" class="row person">
          <span class="avatar" :style="{ background: p.color }">{{ p.emoji || p.name[0] }}</span>
          <span class="pmain">
            <span class="pname">{{ p.name }}</span>
            <span class="bar"><i :style="{ width: pct(p.events) + '%', background: p.color }"></i></span>
          </span>
          <span class="nums">
            {{ p.events }} · {{ Math.round(p.minutes / 6) / 10 }} ч
            <small v-if="p.dropoff || p.pickup">отвёз {{ p.dropoff }}, забрал {{ p.pickup }}</small>
          </span>
        </div>
      </div>

      <h3 class="group-title">По дням недели</h3>
      <div class="group wd">
        <div v-for="d in r.weekdays" :key="d.name" class="col">
          <span class="stick"><i :style="{ height: wpct(d.events) + '%' }"></i></span>
          <small>{{ d.name }}</small><small class="muted">{{ d.events }}</small>
        </div>
      </div>

      <div class="group facts">
        <div v-if="r.busiest_day" class="row"><span class="lbl">Самый загруженный день</span>
          <span class="val muted">{{ dayName(r.busiest_day.date) }}, {{ r.busiest_day.events }} {{ plural(r.busiest_day.events, 'встреча', 'встречи', 'встреч') }}</span></div>
        <div v-for="t in r.top_titles" :key="t.title" class="row"><span class="lbl">{{ t.title }}</span><span class="val muted">× {{ t.count }}</span></div>
      </div>
      <p class="group-note">Считаются встречи со временем (без событий на весь день). Если в событии несколько участников, оно идёт в зачёт каждому.</p>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { isoDate } from '../lib/dates'

const PERIODS = [{ id: 'week', name: 'Неделя' }, { id: 'month', name: 'Месяц' }, { id: 'quarter', name: '3 месяца' }, { id: 'year', name: 'Год' }]
const period = ref('month')
const r = ref(null)
const err = ref('')

function bounds(p) {
  const now = new Date()
  const d0 = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (p === 'week') {
    const s = new Date(d0); s.setDate(s.getDate() - ((s.getDay() + 6) % 7))
    const e = new Date(s); e.setDate(e.getDate() + 7)
    return [s, e]
  }
  if (p === 'month') return [new Date(now.getFullYear(), now.getMonth(), 1), new Date(now.getFullYear(), now.getMonth() + 1, 1)]
  if (p === 'quarter') return [new Date(now.getFullYear(), now.getMonth() - 2, 1), new Date(now.getFullYear(), now.getMonth() + 1, 1)]
  return [new Date(now.getFullYear(), 0, 1), new Date(now.getFullYear() + 1, 0, 1)]
}
const rangeText = computed(() => {
  const [s, e] = bounds(period.value)
  const f = (d) => d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
  return `${f(s)} – ${f(new Date(e - 86400000))}`
})
async function load() {
  const [s, e] = bounds(period.value)
  err.value = ''
  try { r.value = await api.stats(isoDate(s) + 'T00:00', isoDate(e) + 'T00:00') } catch (x) { err.value = x.message }
}
watch(period, load, { immediate: true })

const max = computed(() => Math.max(1, ...(r.value?.people || []).map((p) => p.events)))
const wmax = computed(() => Math.max(1, ...(r.value?.weekdays || []).map((d) => d.events)))
const pct = (n) => Math.round((n / max.value) * 100)
const wpct = (n) => Math.round((n / wmax.value) * 100)
const dayName = (d) => new Date(d + 'T12:00').toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })
function plural(n, a, b, c) {
  const m10 = n % 10, m100 = n % 100
  return m10 === 1 && m100 !== 11 ? a : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? b : c
}
</script>

<style scoped>
.seg { display: flex; gap: 4px; background: var(--fill); border-radius: 10px; padding: 3px; margin-top: 8px; }
.seg button { flex: 1; border: 0; background: none; padding: 7px 4px; border-radius: 8px; font: inherit; font-size: 14px; color: inherit; }
.seg button.on { background: var(--bg-elev, #fff); font-weight: 600; box-shadow: 0 1px 2px rgba(0, 0, 0, .15); }
.range { text-align: center; margin: 8px 0 4px; }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 8px 0; }
.tile { background: var(--fill); border-radius: 14px; padding: 14px 8px; text-align: center; display: flex; flex-direction: column; gap: 2px; }
.tile b { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
.tile span { font-size: 12px; color: var(--ink-3); }
.person { gap: 12px; }
.avatar { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-weight: 600; flex: none; }
.pmain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.pname { font-weight: 500; }
.bar { height: 6px; background: var(--fill); border-radius: 3px; overflow: hidden; display: block; }
.bar i { display: block; height: 100%; border-radius: 3px; }
.nums { text-align: right; font-size: 14px; white-space: nowrap; display: flex; flex-direction: column; }
.nums small { font-size: 11px; color: var(--ink-3); }
.wd { display: flex; padding: 12px; gap: 6px; }
.col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; }
.stick { height: 70px; width: 100%; display: flex; align-items: flex-end; justify-content: center; }
.stick i { width: 60%; max-width: 22px; background: var(--red); border-radius: 4px 4px 0 0; min-height: 2px; }
.facts { margin-top: 10px; }
.err { color: var(--red); }
</style>
