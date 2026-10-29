<template>
  <div class="swatches" role="radiogroup" :aria-label="label">
    <button v-if="noneLabel" class="sw none" :class="{ on: !modelValue }" role="radio" :aria-checked="!modelValue"
            :title="noneLabel" :disabled="disabled" @click="$emit('update:modelValue', null)">
      <span>∅</span>
    </button>
    <button v-for="col in PALETTE" :key="col" role="radio" :aria-checked="modelValue === col" class="sw"
            :class="{ on: modelValue === col }" :style="{ background: col }" :aria-label="col" :disabled="disabled"
            @click="$emit('update:modelValue', col)"></button>
    <label class="sw custom" :class="{ on: !!modelValue && !PALETTE.includes(modelValue) }" title="Свой цвет">
      <input type="color" :value="modelValue || '#5856d6'" :disabled="disabled" @change="$emit('update:modelValue', $event.target.value)" />
    </label>
  </div>
</template>

<script setup>
const PALETTE = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#00c7be', '#007aff', '#5856d6', '#af52de', '#ff2d55', '#a2845e']
defineProps({
  modelValue: { type: String, default: null },
  noneLabel: { type: String, default: '' },   // подпись для «без цвета» (кружок ∅)
  label: { type: String, default: 'Цвет' },
  disabled: Boolean,
})
defineEmits(['update:modelValue'])
</script>

<style scoped>
.swatches { display: flex; flex-wrap: wrap; gap: 10px; }
.sw { width: 30px; height: 30px; border-radius: 50%; border: 0; padding: 0; position: relative; cursor: pointer; }
.sw.on { box-shadow: 0 0 0 2px var(--surface-2), 0 0 0 4px var(--ink-2); }
.sw.none { background: var(--fill); color: var(--ink-2); display: grid; place-items: center; font-size: 16px; }
.sw.custom { background: conic-gradient(#ff3b30, #ffcc00, #34c759, #00c7be, #007aff, #af52de, #ff3b30); overflow: hidden; }
.sw.custom input { opacity: 0; width: 100%; height: 100%; cursor: pointer; }
</style>
