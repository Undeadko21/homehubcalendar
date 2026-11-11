// Голосовой ввод: в Android-приложении — системное распознавание (мост HomeHubApp), в браузере — Web Speech API
// (Chrome, Edge, Safari). Встроенные окна приложений iPhone и Mac его не дают — там кнопки микрофона нет.
const SR = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null
const bridge = typeof window !== 'undefined' ? window.HomeHubApp : null

export const voiceSupported = (() => {
  try { if (bridge?.canVoice) return !!bridge.canVoice() } catch { /* старое приложение */ }
  return !!SR && !(bridge && !bridge.canVoice)   // в старом Android-приложении WebView речь не распознаёт
})()

let current = null
/** Слушает одну фразу. Resolve(text) или reject(Error) — «ничего не расслышал», «нет доступа к микрофону». */
export function listen() {
  if (bridge?.startVoice && voiceSupported) {
    return new Promise((resolve, reject) => {
      window.__hhVoice = (text) => {
        window.__hhVoice = null
        if (text) resolve(text)
        else reject(new Error('Ничего не расслышал'))
      }
      bridge.startVoice()
    })
  }
  if (!SR) return Promise.reject(new Error('Голосовой ввод здесь не поддерживается'))
  stop()
  return new Promise((resolve, reject) => {
    const r = new SR()
    current = r
    r.lang = 'ru-RU'
    r.interimResults = false
    r.maxAlternatives = 1
    let got = false
    r.onresult = (e) => { got = true; resolve(e.results[0][0].transcript) }
    r.onerror = (e) => {
      got = true
      reject(new Error(e.error === 'not-allowed' || e.error === 'service-not-allowed' ? 'Нет доступа к микрофону — разрешите его в браузере'
        : e.error === 'no-speech' ? 'Ничего не расслышал' : 'Не получилось распознать: ' + e.error))
    }
    r.onend = () => { current = null; if (!got) reject(new Error('Ничего не расслышал')) }
    r.start()
  })
}
export function stop() { try { current?.stop() } catch { /* уже остановлен */ } current = null }
