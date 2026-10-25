// Загружает события и особые дни для диапазона, который зависит от состояния.
import { computed, ref, watch } from 'vue'
import { state, fetchRange, isEventVisible } from './store'

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
      const res = await fetchRange(start, end)
      // Проверяем, что за время запроса диапазон не сменился.
      if (+range.value.start === +start && +range.value.end === +end) {
        raw.value = res.events
        holidays.value = res.holidays
        error.value = null
      }
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  watch(() => [+range.value.start, +range.value.end, state.revision], load, { immediate: true })

  const events = computed(() => raw.value.filter(isEventVisible))
  const holidayMap = computed(() => Object.fromEntries(holidays.value.map((h) => [h.date, h])))
  return { events, holidays, holidayMap, loading, error, range, reload: load }
}
