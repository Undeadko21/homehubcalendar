// Загружает события и особые дни для диапазона, который зависит от состояния.
import { computed, ref, watch } from 'vue'
import { state, fetchRange, isEventVisible } from './store'
import { report } from './report'

export function useRange(rangeFn) {
  const raw = ref([])
  const holidays = ref([])
  const loading = ref(false)
  const loaded = ref(false)   // свежий ответ сервера получен хотя бы раз (для пустых состояний)
  const error = ref(null)
  const range = computed(rangeFn)

  async function load() {
    const { start, end } = range.value
    loading.value = true
    try {
      const res = fetchRange(start, end)
      const same = () => +range.value.start === +start && +range.value.end === +end
      res.holidays.then((h) => { if (same()) holidays.value = h })
      // Прошлый ответ для этого диапазона — сразу, свежий заменит его без мигания.
      if (res.cached && same() && !raw.value.length) raw.value = res.cached
      const evs = await res.events
      // Проверяем, что за время запроса диапазон не сменился.
      if (same()) {
        raw.value = evs
        error.value = null
        loaded.value = true
      }
    } catch (e) {
      error.value = e.message
      if (e.offline) return   // нет связи — полоса «Нет связи с домом» уже на экране, баннер ошибки не нужен
      report('Не удалось загрузить события: ' + e.message, { stack: e.stack, kind: 'events' })
    } finally {
      loading.value = false
    }
  }

  watch(() => [+range.value.start, +range.value.end, state.revision], load, { immediate: true })

  const events = computed(() => raw.value.filter(isEventVisible))
  const holidayMap = computed(() => Object.fromEntries(holidays.value.map((h) => [h.date, h])))
  return { events, holidays, holidayMap, loading, loaded, error, range, reload: load }
}
