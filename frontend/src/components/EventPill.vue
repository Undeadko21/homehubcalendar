<template>
  <button
    class="pill"
    :class="{ allday: e.all_day && !e.private, past, private: e.private, now: current }"
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
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { openEvent, eventColor, personById } from '../lib/store'
import { eventRange, formatEventTime } from '../lib/dates'

const props = defineProps({
  e: { type: Object, required: true },
  now: { type: Date, default: null },     // передайте текущее время, чтобы гасить прошедшие
  hideMeta: Boolean,
  ownerId: { type: String, default: null }, // в ленте конкретного человека — показываем остальных участников точками
})

const color = computed(() => {
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
.pill.now { box-shadow: 0 0 0 2px var(--c); }
.dots { margin-right: 4px; }
</style>
