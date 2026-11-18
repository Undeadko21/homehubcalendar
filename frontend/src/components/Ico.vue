<template>
  <svg class="i" :class="'i-' + name" viewBox="0 0 24 24" :width="size" :height="size" aria-hidden="true" focusable="false">
    <path v-for="(d, k) in paths" :key="k" :d="d" :fill="fill(k)" />
  </svg>
</template>

<script setup>
// Линейный значок из lib/ico.js: <Ico name="edit" />
import { computed } from 'vue'
import { ICONS } from '../lib/ico'

const props = defineProps({ name: { type: String, required: true }, size: { type: [Number, String], default: '1em' } })

const paths = computed(() => (ICONS[props.name] || []).map((d) => d.replace(/^F:/, '')))
const fill = (k) => ((ICONS[props.name] || [])[k] || '').startsWith('F:') ? 'currentColor' : 'none'
</script>

<style scoped>
.i { display: inline-block; vertical-align: -0.14em; flex: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
</style>
