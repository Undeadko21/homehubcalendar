<template>
  <div v-if="e" class="backdrop" @click.self="close" @keydown.esc="close">
    <section ref="box" class="dialog" role="dialog" aria-modal="true" :aria-label="e.title" tabindex="-1" :style="{ '--c': color }">
      <div class="band"></div>
      <button class="x" aria-label="Закрыть" @click="close">×</button>
      <h2>{{ e.title }}</h2>
      <p class="when">
        {{ dayLabel }}, {{ formatEventTime(e) }}
        <span v-if="e.recurring" class="tag">повторяется</span>
        <span v-if="e.tentative" class="tag">под вопросом</span>
      </p>
      <div class="who">
        <span v-for="p in persons" :key="p.id" class="person" :style="{ '--c': p.color }">
          <i></i>{{ p.emoji }} {{ p.name }}
        </span>
      </div>
      <p v-if="e.location" class="row">
        <span class="k">Где</span>
        <a :href="mapUrl" target="_blank" rel="noopener">{{ e.location }}</a>
      </p>
      <p v-if="e.url" class="row"><span class="k">Ссылка</span><a :href="e.url" target="_blank" rel="noopener">{{ e.url }}</a></p>
      <p v-if="e.description" class="desc">{{ e.description }}</p>
      <p v-if="e.private" class="faint">Детали скрыты: у этого календаря в настройках включено «только занят».</p>
      <p class="faint src">Календари: {{ calNames }}</p>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { state, personById, eventColor } from '../lib/store'
import { eventRange, formatEventTime, relativeDayName } from '../lib/dates'

const box = ref(null)
const e = computed(() => state.selected)
const color = computed(() => (e.value ? eventColor(e.value) : '#888'))
const persons = computed(() => (e.value?.people || []).map((id) => personById.value[id]).filter(Boolean))
const dayLabel = computed(() => (e.value ? relativeDayName(eventRange(e.value).start) : ''))
const mapUrl = computed(() => 'https://yandex.ru/maps/?text=' + encodeURIComponent(e.value?.location || ''))
const calNames = computed(() => {
  const all = state.config?.calendars || []
  return (e.value?.calendars || []).map((k) => all.find((c) => c.key === k)?.name || k).join(', ')
})

function close() { state.selected = null }
watch(e, async (v) => {
  if (v) { await nextTick(); box.value?.focus() }
})
</script>

<style scoped>
.backdrop { position: fixed; inset: 0; background: rgba(15, 20, 30, .45); display: grid; place-items: center; z-index: 50; padding: 16px; }
.dialog {
  --c: #888;
  position: relative; width: min(480px, 100%); max-height: 85vh; overflow: auto;
  background: var(--surface); border-radius: var(--radius-l); box-shadow: var(--shadow);
  padding: 22px 24px 18px; outline: none;
}
.band { position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: var(--c); }
.x { position: absolute; top: 10px; right: 12px; border: 0; background: none; font-size: 26px; line-height: 1; color: var(--ink-2); }
h2 { margin: 0 32px 4px 0; font-size: 22px; line-height: 1.25; letter-spacing: -0.01em; }
.when { margin: 0 0 12px; color: var(--ink-2); }
.tag { display: inline-block; font-size: 12px; background: var(--surface-2); border-radius: 999px; padding: 1px 8px; margin-left: 6px; }
.who { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.person { --c: #888; display: inline-flex; align-items: center; gap: 6px; background: color-mix(in srgb, var(--c) 14%, var(--surface)); border-radius: 999px; padding: 3px 10px 3px 8px; font-weight: 600; font-size: 14px; }
.person i { width: 8px; height: 8px; border-radius: 50%; background: var(--c); }
.row { margin: 6px 0; display: flex; gap: 10px; overflow-wrap: anywhere; }
.k { color: var(--ink-3); min-width: 56px; }
.desc { white-space: pre-wrap; background: var(--surface-2); border-radius: var(--radius-m); padding: 10px 12px; margin: 12px 0 0; overflow-wrap: anywhere; }
.src { font-size: 13px; margin: 14px 0 0; }
</style>
