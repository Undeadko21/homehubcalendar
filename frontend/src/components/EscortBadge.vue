<template>
  <span class="escort" :class="e.escort_issue || 'ok'">
    <span v-if="e.escort.mode === 'home'" class="role mode">⌂ дома</span>
    <span v-else-if="e.escort.mode === 'together'" class="role mode">все вместе</span>
    <span v-for="r in roles" :key="r.role" class="role" :class="{ bad: r.conflict, none: r.missing }" :title="r.title">
      <span class="dir" aria-hidden="true">{{ r.role === 'dropoff' ? '→' : '←' }}</span>
      {{ r.label }}
    </span>
  </span>
</template>

<script setup>
// Короткая строка «→ Оля  ← Толя» под событием ребёнка; красным — конфликт, оранжевым — никто не назначен.
import { computed } from 'vue'
import { personById } from '../lib/store'

const props = defineProps({ e: { type: Object, required: true } })
const roles = computed(() =>
  ['dropoff', 'pickup']
    .map((role) => ({ role, r: props.e.escort[role] }))
    .filter(({ r }) => !r.skip)
    .map(({ role, r }) => {
      const verb = role === 'dropoff' ? 'Отвезти' : 'Забрать'
      const name = r.person ? personById.value[r.person]?.name || r.person : 'кто?'
      return {
        role,
        label: name,
        conflict: r.conflicts.length > 0,
        missing: !r.person,
        title: `${verb}: ${r.person ? name : 'никто не назначен'}${r.conflicts.length ? ' — занят(а): ' + r.conflicts.map((c) => c.title).join(', ') : ''}`,
      }
    }),
)
</script>

<style scoped>
.escort { display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px; font-weight: 600; color: var(--ink-2); }
.role { display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; }
.dir { font-weight: 700; }
.role.none { color: var(--warn); }
.role.mode { font-weight: 500; }
.role.bad { color: var(--red); }
.role.bad::after { content: '!'; display: inline-grid; place-items: center; width: 14px; height: 14px; border-radius: 50%; background: var(--red); color: #fff; font-size: 10px; margin-left: 2px; }
</style>
