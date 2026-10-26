<template>
  <div class="picker" role="group" :aria-label="label">
    <button
      v-for="p in options"
      :key="p.id"
      type="button"
      class="opt"
      :class="{ on: modelValue.includes(p.id) }"
      :style="{ '--c': p.color }"
      :aria-pressed="modelValue.includes(p.id)"
      :disabled="disabled"
      @click="toggle(p.id)"
    >
      <span class="mark" aria-hidden="true">{{ modelValue.includes(p.id) ? '✓' : '' }}</span>
      <span v-if="p.emoji">{{ p.emoji }}</span>
      {{ p.name }}
    </button>
  </div>
</template>

<script setup>
// Выбор нескольких людей «таблетками». v-model — массив id.
import { computed } from 'vue'
import { state } from '../lib/store'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  label: { type: String, default: 'Люди' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])

const options = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_')))

function toggle(id) {
  const next = props.modelValue.includes(id)
    ? props.modelValue.filter((x) => x !== id)
    : [...props.modelValue, id]
  // сохраняем порядок как в списке людей
  const order = options.value.map((p) => p.id)
  emit('update:modelValue', next.sort((a, b) => order.indexOf(a) - order.indexOf(b)))
}
</script>

<style scoped>
.picker { display: flex; flex-wrap: wrap; gap: 6px; }
.opt {
  --c: #888;
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink-2);
  border-radius: 999px; padding: 5px 12px 5px 6px; font-size: 14px; line-height: 1.2;
}
.mark {
  width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center;
  box-shadow: inset 0 0 0 2px var(--c); font-size: 11px; font-weight: 800; color: #fff;
}
.opt.on { background: color-mix(in srgb, var(--c) 14%, var(--surface)); border-color: color-mix(in srgb, var(--c) 50%, var(--line)); color: var(--ink); font-weight: 600; }
.opt.on .mark { background: var(--c); box-shadow: none; }
.opt:disabled { opacity: .6; cursor: default; }
</style>
