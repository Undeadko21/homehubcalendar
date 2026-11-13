<template>
  <div class="news">
    <div v-for="x in NEWS" :key="x.n" class="group item">
      <div class="row stack">
        <span class="head"><strong>{{ x.title }}</strong><span v-if="isNew(x)" class="badge">новое</span></span>
        <span class="txt">{{ x.text }}</span>
        <span v-if="x.action" class="act">
          <template v-if="x.action.toggle">
            <button v-if="!state[x.action.toggle]" class="btn filled sm" @click="turnOn(x.action.toggle)">{{ x.action.label }}</button>
            <span v-else class="on">✓ Включено <button class="btn link sm" @click="turnOff(x.action.toggle)">выключить</button></span>
          </template>
          <button v-else class="btn sm tint" @click="go(x.action)">{{ x.action.label }} ›</button>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
// «Что нового»: что появилось и как это включить. Открытие страницы гасит точку у «Настроек».
import { onMounted } from 'vue'
import { state, setIcons, setInitials, setView } from '../lib/store'
import { NEWS, isNew, markNewsSeen } from '../lib/news'

const emit = defineEmits(['goto'])
onMounted(markNewsSeen)
const SET = { icons: setIcons, initials: setInitials }
const turnOn = (k) => SET[k](true)
const turnOff = (k) => SET[k](false)
function go(a) {
  if (a.page) emit('goto', a.page)
  else if (a.quick) state.quickAdd = true
  else if (a.view) setView(a.view)
}
</script>

<style scoped>
.item { margin-bottom: 10px; }
.head { display: flex; align-items: center; gap: 8px; }
.head strong { font-size: 16px; }
.badge { font-size: 11px; font-weight: 700; color: #fff; background: var(--red); border-radius: 999px; padding: 1px 8px; }
.txt { color: var(--ink-2); font-size: 14px; line-height: 1.4; }
.act { margin-top: 6px; }
.tint { color: var(--tint); font-weight: 600; padding-left: 0; }
.on { color: var(--ok); font-size: 14px; font-weight: 600; }
</style>
