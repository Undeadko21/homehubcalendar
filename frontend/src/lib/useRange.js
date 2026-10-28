// Загружает события и особые дни для диапазона, который зависит от состояния.
import { computed, ref, watch } from 'vue'
import { state, fetchRange, isEventVisible } from './store'
import { report } from './report'

export function useRange(rangeFn) {
  const raw = ref([])
  const holidays = ref([])
  const loading = ref(false)
  const error = ref(null)
  const range = computed(rangeFn)

  async function load() {
    const { start, end } = range.value
    loading.value = true
    try {
      const res = fetchRange(start, end)
      const same = () => +range.value.start === +start && +range.value.end === +end
      res.holidays.then((h) => { if (same()) holidays.value = h })
      const evs = await res.events
      // Проверяем, что за время запроса диапазон не сменился.
      if (same()) {
        raw.value = evs
        error.value = null
      }
    } catch (e) {
      error.value = e.message
      report('Не удалось загрузить события: ' + e.message, { stack: e.stack, kind: 'events' })
    } finally {
      loading.value = false
    }
  }

  watch(() => [+range.value.start, +range.value.end, state.revision], load, { immediate: true })

  const events = computed(() => raw.value.filter(isEventVisible))
  const holidayMap = computed(() => Object.fromEntries(holidays.value.map((h) => [h.date, h])))
  return { events, holidays, holidayMap, loading, error, range, reload: load }
}
