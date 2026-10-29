<template>
  <button
    class="pill"
    :class="{ allday: e.all_day && !e.private, past, private: e.private, now: current, issue: e.escort_issue, duty: e.duty, conflict: e.duty && e.escort_issue === 'conflict' }"
    :style="{ '--c': color }"
    @click="openEvent(e)"
  >
    <span class="t">
      <span v-if="others.length" class="dots" aria-hidden="true">
        <i v-for="p in others" :key="p.id" :style="{ '--c': p.color }"></i>
      </span>
      {{ e.title }}
    </span>
    <span v-if="!hideMeta && meta" class="s">{{ meta }}</span>
    <EscortBadge v-if="e.escort && !hideEscort" :e="e" class="esc" />
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { openEvent, eventColor, personById } from '../lib/store'
import { eventRange, formatEventTime } from '../lib/dates'
import EscortBadge from './EscortBadge.vue'

const props = defineProps({
  e: { type: Object, required: true },
  now: { type: Date, default: null },     // передайте текущее время, чтобы гасить прошедшие
  hideMeta: Boolean,
  hideEscort: Boolean,
  ownerId: { type: String, default: null }, // в колонке конкретного человека — остальные участники точками
})

const color = computed(() => {
  if (props.e.color) return props.e.color
  if (props.ownerId) return personById.value[props.ownerId]?.color || eventColor(props.e)
  return eventColor(props.e)
})
const others = computed(() =>
  props.e.people.length > 1
    ? props.e.people.filter((id) => id !== props.ownerId).map((id) => personById.value[id]).filter(Boolean)
    : [],
)
const r = computed(() => eventRange(props.e))
const past = computed(() => props.now && !props.e.all_day && r.value.end <= props.now)
const current = computed(() => props.now && !props.e.all_day && r.value.start <= props.now && r.value.end > props.now)
const meta = computed(() => {
  const parts = []
  if (!props.e.all_day) parts.push(formatEventTime(props.e))
  if (props.e.location) parts.push(props.e.location)
  return parts.join(', ')
})
</script>

<style scoped>
.pill.now { box-shadow: inset 0 0 0 1.5px var(--c); }
.pill.conflict { box-shadow: inset 0 0 0 1.5px var(--red); }
.pill.issue { padding-bottom: 6px; }
.dots { margin-right: 4px; }
.esc { margin-top: 4px; }
</style>
