<template>
  <div class="people" role="group" aria-label="Чьи события показывать">
    <button
      v-for="p in people"
      :key="p.id"
      class="chip"
      :class="{ off: state.hiddenPeople.includes(p.id) }"
      :style="{ '--c': p.color }"
      :aria-pressed="!state.hiddenPeople.includes(p.id)"
      title="Нажмите, чтобы скрыть или показать. Двойное нажатие — только этот человек."
      @click="togglePerson(p.id)"
      @dblclick.prevent="showOnly(p.id)"
    >
      <span class="dot"></span>
      <span v-if="p.emoji" class="emoji">{{ p.emoji }}</span>
      {{ p.name }}
    </button>
    <button v-if="state.hiddenPeople.length" class="chip all" @click="showAll">Показать всех</button>
  </div>
</template>

<script setup>
import { state, people, togglePerson, showOnly, showAll } from '../lib/store'
</script>

<style scoped>
.people { display: flex; gap: 8px; padding: 10px 20px; overflow-x: auto; border-bottom: 1px solid var(--line); }
.chip {
  --c: #8a94a6;
  display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  border: 1px solid color-mix(in srgb, var(--c) 45%, var(--line));
  background: color-mix(in srgb, var(--c) 12%, var(--surface));
  border-radius: 999px; padding: 4px 12px 4px 8px; font-weight: 600;
}
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--c); }
.emoji { font-size: 16px; line-height: 1; }
.chip.off { background: transparent; border-color: var(--line); color: var(--ink-3); font-weight: 500; }
.chip.off .dot { background: transparent; box-shadow: inset 0 0 0 2px var(--c); }
.chip.all { border-style: dashed; font-weight: 500; color: var(--ink-2); background: none; padding-left: 12px; }
@media (max-width: 760px) { .people { padding: 8px 12px; } }
</style>
