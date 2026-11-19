<template>
  <div class="ip">
    <div class="grid" role="radiogroup" :aria-label="label">
      <button class="ic txt" :class="{ on: modelValue === null }" role="radio" :aria-checked="modelValue === null"
              :disabled="disabled" title="Значок по словам в названии" @click="$emit('update:modelValue', null)">Авто</button>
      <button class="ic txt" :class="{ on: modelValue === '' }" role="radio" :aria-checked="modelValue === ''"
              :disabled="disabled" title="Без значка" @click="$emit('update:modelValue', '')">Нет</button>
      <button v-for="i in ICONS" :key="i" class="ic" :class="{ on: modelValue === i }" role="radio" :aria-checked="modelValue === i"
              :aria-label="i" :disabled="disabled" @click="$emit('update:modelValue', i)">{{ i }}</button>
    </div>
  </div>
</template>

<script setup>
// Набор для выбора своего значка события (карточка события → «Значок»). Автоматические — lib/icons.js.
const ICONS = ['🏊', '⚽', '🏒', '🏀', '🎾', '🏋️', '🥋', '⛷️', '💃', '🎵', '🎨', '♟️', '🤖', '📚', '🧸', '🩺', '🦷', '💊',
  '🗣️', '🎂', '🎉', '🍽️', '🎭', '🛒', '💇', '🚗', '✈️', '🚆', '🧳', '🏡', '🐾', '💼', '💳', '🧹', '⭐', '❤️']
defineProps({
  modelValue: { type: String, default: null },   // null — авто, '' — без значка
  label: { type: String, default: 'Значок' },
  disabled: Boolean,
})
defineEmits(['update:modelValue'])
</script>

<style scoped>
.grid { display: flex; flex-wrap: wrap; gap: 6px; }
.ic { min-width: 40px; height: 40px; border-radius: 10px; border: 0; background: transparent; box-shadow: inset 0 0 0 1px var(--sep, rgba(127,127,127,.25)); font-size: 20px; line-height: 1;
  padding: 0 6px; cursor: pointer; color: var(--ink); }
.ic.txt { font-size: 13px; color: var(--ink-2); padding: 0 10px; }
.ic.on { box-shadow: 0 0 0 2px var(--accent, #ff3b30); background: var(--surface-2); }
.ic:disabled { opacity: .5; }
</style>
