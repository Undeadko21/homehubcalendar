// Лёгкий отклик на важные нажатия: назначили водителя, отметили покупку, перенесли событие.
// В Android-приложении — системный отклик (мост HomeHubApp.haptic, без разрешений), в браузере телефона — navigator.vibrate.
// Отключается в «Внешнем виде» (state.haptics).
import { state } from './store'

const PATTERN = { tap: 12, success: [10, 40, 18], warn: [30, 60, 30] }
export function haptic(kind = 'tap') {
  if (state.haptics === false) return
  try {
    if (window.HomeHubApp?.haptic) { window.HomeHubApp.haptic(kind); return }
    if (navigator.vibrate && matchMedia('(pointer: coarse)').matches) navigator.vibrate(PATTERN[kind] || 12)
  } catch { /* не поддерживается — молча */ }
}
