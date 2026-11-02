// Копирование в буфер. navigator.clipboard работает только по https и на localhost, а сервер у нас обычно по http://адрес-в-сети,
// поэтому запасной путь — выделение в скрытом поле и execCommand('copy') (в том числе для iOS Safari).
export async function copyToClipboard(text) {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* пробуем запасной способ */ }
  const a = document.createElement('textarea')
  a.value = text
  a.setAttribute('readonly', '')
  a.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px'
  document.body.appendChild(a)
  try {
    a.focus({ preventScroll: true })
    a.select()
    a.setSelectionRange(0, text.length)
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    a.remove()
  }
}
