<template>
  <Sheet :open="state.onboarding" label="Знакомство с календарём" @close="finish">
    <div class="ob">
      <div class="dots" aria-hidden="true"><i v-for="n in STEPS" :key="n" :class="{ on: n - 1 === step }"></i></div>

      <template v-if="step === 0">
        <h2>Чьи события показывать</h2>
        <p class="lead">Выберите, чей календарь вам нужен на этом устройстве. Остальных всегда можно вернуть в разделе «Люди».</p>
        <PeopleList />
      </template>

      <template v-else-if="step === 1">
        <h2>Напоминания</h2>
        <template v-if="inApp">
          <p class="lead">Чьи поездки и встречи напоминать на этом телефоне. По умолчанию выключено — каждый выбирает сам.</p>
          <RemindersSettings />
        </template>
        <template v-else>
          <p class="lead">Уведомления показывают приложения: Android, iPhone и Mac. В браузере их нет.</p>
          <div class="group"><button class="row link" @click="goSettings('app')">Скачать приложение ›</button></div>
          <p class="faint small">В приложении включите напоминания в «Настройки → Напоминания» и выберите, чьи поездки и встречи вам важны.</p>
        </template>
      </template>

      <template v-else-if="step === 2">
        <h2>Вне дома</h2>
        <p class="lead">Чтобы календарь, виджет и напоминания работали не только в домашней сети, подключите устройство одним кодом или QR.</p>
        <div class="group"><button class="row link" @click="goSettings('outside')">Открыть «Связь вне дома» ›</button></div>
        <p class="faint small">Достаточно сделать один раз на каждом устройстве. Дома всё работает и без этого.</p>
      </template>

      <template v-else>
        <h2>Виджет и быстрые действия</h2>
        <ul class="tips">
          <li><b>Виджет.</b> Добавьте «HomeHub Calendar» на домашний экран телефона — сегодня и завтра без открытия приложения.</li>
          <li><b>Кнопка «+».</b> Одной фразой: «Йога завтра в 18:30», «купить молоко», «дело: оплатить кружок до пятницы».</li>
          <li><b>Перенос.</b> Перетащите событие на другое время или день; ошиблись — «Отменить» внизу экрана.</li>
          <li><b>Поездки детей.</b> В карточке события ребёнка выберите, кто отвозит и забирает.</li>
        </ul>
        <div class="group"><button class="row link" @click="goSettings('app')">Приложения и виджеты ›</button></div>
      </template>

      <div class="nav">
        <button v-if="step > 0" class="btn gray" @click="step--">Назад</button>
        <button v-else class="btn" @click="finish">Пропустить</button>
        <button class="btn filled" @click="step < STEPS - 1 ? step++ : finish()">{{ step < STEPS - 1 ? 'Дальше' : 'Готово' }}</button>
      </div>
    </div>
  </Sheet>
</template>

<script setup>
// Знакомство для нового устройства: 4 коротких шага. Показывается один раз (и по кнопке в «Внешнем виде»).
import { onMounted, ref, watch } from 'vue'
import { state, finishOnboarding, setView, people } from '../lib/store'
import Sheet from './Sheet.vue'
import PeopleList from './PeopleList.vue'
import RemindersSettings from './RemindersSettings.vue'

const STEPS = 4
const step = ref(0)
const inApp = typeof window !== 'undefined' && !!window.HomeHubApp

watch(() => state.onboarding, (v) => { if (v) step.value = 0 })
// Первый запуск на устройстве: когда настройки загружены, есть люди и это не экран на стене.
onMounted(() => {
  const stop = watch(() => people.value.length, (n) => {
    if (!n) return
    if (!state.onboarded && !state.kiosk && !new URLSearchParams(location.search).has('nointro')) state.onboarding = true
    setTimeout(() => stop(), 0)
  }, { immediate: true })
})

function finish() { finishOnboarding() }
function goSettings(page) {
  try { sessionStorage.setItem('settingsPage', page) } catch { /* без хранилища */ }
  finish()
  setView('settings')
}
</script>

<style scoped>
.ob { padding: 6px 2px 4px; display: flex; flex-direction: column; gap: 12px; }
.dots { display: flex; gap: 6px; justify-content: center; }
.dots i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); opacity: .4; }
.dots i.on { background: var(--tint); opacity: 1; }
h2 { margin: 6px 0 0; font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }
.lead { margin: 0; color: var(--ink-2); line-height: 1.4; }
.group { background: var(--surface-2); }
.row.link { width: 100%; border: 0; background: none; text-align: left; font: inherit; color: var(--tint); font-weight: 600; }
.tips { margin: 0; padding: 0 0 0 18px; display: flex; flex-direction: column; gap: 8px; line-height: 1.4; }
.small { font-size: 13px; margin: 0; }
.nav { display: flex; justify-content: space-between; gap: 8px; margin-top: 8px; }
.nav .filled { min-width: 120px; }
</style>
