<template>
  <div class="plist">
    <div class="ph">
      <span>Люди</span>
      <button v-if="state.hiddenPeople.length" class="btn sm" @click="showAll">Показать всех</button>
    </div>
    <button
      v-for="p in people" :key="p.id" class="person"
      :aria-pressed="!state.hiddenPeople.includes(p.id)"
      :style="{ '--c': p.color }"
      title="Нажмите, чтобы скрыть или показать. Двойное нажатие — только этот человек."
      @click="togglePerson(p.id)" @dblclick.prevent="showOnly(p.id)"
    >
      <span class="check" :class="{ on: !state.hiddenPeople.includes(p.id) }" aria-hidden="true">
        <svg v-if="!state.hiddenPeople.includes(p.id)" viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.6l4.6-5" /></svg>
      </span>
      <span class="name">{{ p.emoji ? p.emoji + ' ' : '' }}{{ p.name }}</span>
      <span v-if="p.needs_escort" class="tag">ребёнок</span>
    </button>
  </div>
</template>

<script setup>
// Список людей с цветными галочками — как список календарей в боковой панели macOS.
import { state, people, togglePerson, showOnly, showAll } from '../lib/store'
</script>

<style scoped>
.ph { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 600; color: var(--ink-2); padding: 0 6px 4px 8px; min-height: 26px; }
.sm { font-size: 12px; padding: 2px 6px; }
.person {
  --c: #8e8e93; display: flex; align-items: center; gap: 9px; width: 100%;
  border: 0; background: none; padding: 5px 8px; border-radius: 7px; text-align: left; font-size: 14px;
}
.person:hover { background: var(--fill); }
.check {
  width: 16px; height: 16px; border-radius: 4px; flex: none; display: grid; place-items: center;
  box-shadow: inset 0 0 0 1.5px var(--c);
}
.check.on { background: var(--c); box-shadow: none; }
.check svg { width: 12px; height: 12px; fill: none; stroke: #fff; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { font-size: 11px; color: var(--ink-3); }
</style>
