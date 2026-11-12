<template>
  <div class="skel" role="status" aria-label="Загружаю…">
    <template v-for="n in rows" :key="n">
      <i v-if="blocks" class="blk" :style="{ width: (70 + ((n * 37) % 30)) + '%' }"></i>
      <template v-else>
        <i :style="{ width: (45 + ((n * 23) % 40)) + '%' }"></i>
        <i :style="{ width: (25 + ((n * 17) % 30)) + '%', height: '10px', opacity: .7 }"></i>
      </template>
    </template>
  </div>
</template>

<script setup>
// Серые заглушки строк, пока данные загружаются впервые (вместо пустого экрана).
defineProps({ rows: { type: Number, default: 4 }, blocks: Boolean })
</script>
