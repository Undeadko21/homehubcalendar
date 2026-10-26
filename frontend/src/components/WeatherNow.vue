<template>
  <div v-if="w" class="weather" :title="cfg.city || ''">
    <span class="temp">{{ w.t > 0 ? '+' : '' }}{{ w.t }}°</span>
    <span class="desc">
      {{ w.text }}<br />
      <span class="faint">{{ w.min }}…{{ w.max }}°<template v-if="w.rain >= 30">, дождь {{ w.rain }}%</template></span>
    </span>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { state } from '../lib/store'

const cfg = computed(() => state.config?.weather || {})
const w = ref(null)

const CODES = {
  0: 'Ясно', 1: 'Почти ясно', 2: 'Переменная облачность', 3: 'Пасмурно', 45: 'Туман', 48: 'Туман',
  51: 'Морось', 53: 'Морось', 55: 'Морось', 56: 'Ледяная морось', 57: 'Ледяная морось',
  61: 'Небольшой дождь', 63: 'Дождь', 65: 'Сильный дождь', 66: 'Ледяной дождь', 67: 'Ледяной дождь',
  71: 'Небольшой снег', 73: 'Снег', 75: 'Сильный снег', 77: 'Снежная крупа',
  80: 'Ливень', 81: 'Ливень', 82: 'Сильный ливень', 85: 'Снегопад', 86: 'Сильный снегопад',
  95: 'Гроза', 96: 'Гроза с градом', 99: 'Гроза с градом',
}

async function load() {
  const { latitude, longitude } = cfg.value
  if (latitude == null || longitude == null) return
  try {
    const q = new URLSearchParams({
      latitude, longitude, timezone: 'auto', forecast_days: 1,
      current: 'temperature_2m,weather_code',
      daily: 'temperature_2m_max,temperature_2m_min,precipitation_probability_max',
    })
    const r = await fetch('https://api.open-meteo.com/v1/forecast?' + q)
    const d = await r.json()
    w.value = {
      t: Math.round(d.current.temperature_2m),
      text: CODES[d.current.weather_code] || '',
      min: Math.round(d.daily.temperature_2m_min[0]),
      max: Math.round(d.daily.temperature_2m_max[0]),
      rain: d.daily.precipitation_probability_max?.[0] ?? 0,
    }
  } catch { /* погода не критична — тихо пропускаем */ }
}

let t
onMounted(() => { load(); t = setInterval(load, 30 * 60000) })
onUnmounted(() => clearInterval(t))
</script>

<style scoped>
.weather { display: flex; align-items: center; gap: 12px; }
.temp { font-size: 48px; font-weight: 300; letter-spacing: -0.03em; line-height: 1; }
.desc { font-size: 15px; line-height: 1.35; }
</style>
