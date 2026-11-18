<template>
  <section v-if="cur.length || next || go" class="nn" aria-label="Сейчас и дальше">
    <div v-for="c in cur" :key="c.e.id" class="ln now" :style="{ '--c': c.color }" @click="openEvent(c.e)">
      <i class="dot" aria-hidden="true"></i>
      <span class="k">Сейчас</span>
      <span class="v"><strong>{{ c.e.title }}</strong> <span class="p">· {{ c.who }}</span> <span class="p">· до {{ formatTime(c.end) }}</span></span>
    </div>
    <div v-if="next" class="ln" :style="{ '--c': next.color }" @click="openEvent(next.e)">
      <span class="k">Дальше</span>
      <span class="v"><strong>{{ formatTime(next.start) }} {{ next.e.title }}</strong> <span class="p">· {{ next.who }}</span> <span class="p">· {{ inText(next.start) }}</span></span>
    </div>
    <div v-if="go" class="ln go" :style="{ '--c': go.color }">
      <span class="k"><Ico name="car" /> Выезд</span>
      <span class="v" @click="openEvent(go.e)"><strong>в {{ formatTime(go.at) }}</strong> <span class="p">· {{ go.text }}</span> <span class="p">· {{ inText(go.at) }}</span></span>
      <a v-if="go.e.location" class="route" :href="'https://yandex.ru/maps/?rtt=auto&rtext=~' + encodeURIComponent(go.e.location)"
         target="_blank" rel="noopener"><Ico name="route" /> Маршрут</a>
    </div>
  </section>
</template>

<script setup>
// «Сейчас и дальше» над сеткой «Сегодня»: что идёт, что следующее и когда выезжать на ближайшую поездку ребёнка.
import { computed } from 'vue'
import Ico from './Ico.vue'
import { openEvent, eventColor, personById } from '../lib/store'
import { eventRange, formatTime } from '../lib/dates'

const props = defineProps({ events: { type: Array, required: true }, now: { type: Date, required: true } })
const names = (ids) => ids.filter((p) => !p.startsWith('_')).map((p) => personById.value[p]?.name).filter(Boolean).join(', ') || 'все'
const timed = computed(() => props.events.filter((e) => !e.all_day && !e.duty && !e.absent))

const cur = computed(() => timed.value.map((e) => ({ e, ...eventRange(e) }))
  .filter((x) => x.start <= props.now && x.end > props.now)
  .slice(0, 3).map((x) => ({ ...x, color: eventColor(x.e), who: names(x.e.people) })))

const next = computed(() => {
  const x = timed.value.map((e) => ({ e, ...eventRange(e) })).filter((y) => y.start > props.now).sort((a, b) => a.start - b.start)[0]
  return x ? { ...x, color: eventColor(x.e), who: names(x.e.people) } : null
})

// Выезд: «отвезти» — начало окна (уже с дорогой и запасом); «забрать» — конец события минус дорога и запас.
const go = computed(() => {
  const out = []
  for (const e of timed.value) {
    const esc = e.escort
    if (!esc || esc.mode !== 'escort') continue
    const tr = (esc.travel?.minutes ?? null)
    for (const role of ['dropoff', 'pickup']) {
      const r = esc[role]
      if (!r || r.skip || !r.person || !r.window) continue
      const w0 = new Date(r.window[0])
      const at = role === 'dropoff' ? w0 : (tr != null ? new Date(+w0 - (tr + (esc.travel.buffer || 0)) * 60000) : null)
      if (!at || at < new Date(+props.now - 5 * 60000)) continue
      const kid = names(esc.children || [])
      out.push({ e, at, color: personById.value[r.person]?.color || eventColor(e),
        text: `${personById.value[r.person]?.name || ''} ${role === 'dropoff' ? 'отвозит' : 'забирает'} ${kid} (${e.title})` })
    }
  }
  return out.sort((a, b) => a.at - b.at)[0] || null
})

function inText(d) {
  const m = Math.round((d - props.now) / 60000)
  if (m <= 0) return 'сейчас'
  if (m < 60) return `через ${m} мин`
  const h = Math.floor(m / 60), mm = m % 60
  return `через ${h} ч${mm ? ' ' + mm + ' мин' : ''}`
}
</script>

<style scoped>
.nn { display: flex; flex-direction: column; gap: 6px; max-width: 760px; }
.ln { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 12px; cursor: pointer;
  background: color-mix(in srgb, var(--c) 12%, var(--surface)); box-shadow: inset 3px 0 0 var(--c); flex-wrap: wrap; }
.k { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: color-mix(in srgb, var(--c) var(--ev-mix), var(--ink)); min-width: 64px; display: inline-flex; gap: 4px; align-items: center; }
.v { flex: 1; min-width: 0; font-size: 15px; color: var(--ink-2); }
.v strong { color: var(--ink); font-weight: 600; }
.v .p { white-space: nowrap; }   /* «· до 16:00» не рвётся посередине */
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c); flex: none; animation: nn-pulse 1.8s ease-in-out infinite; }
@keyframes nn-pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 55%, transparent); } 50% { box-shadow: 0 0 0 6px transparent; } }
.route { margin-left: auto; font-size: 14px; font-weight: 600; color: var(--tint); text-decoration: none; display: inline-flex; gap: 4px; align-items: center; }
</style>
