<template>
  <details class="help">
    <summary>{{ title }}</summary>
    <div class="body"><slot /></div>
  </details>
</template>

<script setup>
defineProps({ title: { type: String, default: 'Как это работает' } })
</script>

<style scoped>
.help { margin: 8px 16px 0; font-size: 13px; color: var(--ink-2); }
.help summary { cursor: pointer; color: var(--red); list-style: none; display: inline-flex; align-items: center; gap: 4px; padding: 4px 0; }
.help summary::-webkit-details-marker { display: none; }
.help summary::before { content: '›'; display: inline-block; transition: transform .15s; font-size: 16px; line-height: 1; }
.help[open] summary::before { transform: rotate(90deg); }
.body { padding: 2px 0 6px; line-height: 1.45; }
.body :deep(p) { margin: 4px 0 8px; }
</style>
