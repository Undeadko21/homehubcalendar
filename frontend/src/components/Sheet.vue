<template>
  <Teleport to="body">
    <Transition name="sh">
    <div v-if="open" class="backdrop" @click.self="close" @keydown.esc="close">
      <section ref="box" class="sheet" role="dialog" aria-modal="true" :aria-label="label" tabindex="-1" :style="origin">
        <div class="grabber" aria-hidden="true" @touchstart.passive="dragStart" @touchmove.passive="dragMove" @touchend="dragEnd" @touchcancel="dragCancel"></div>
        <header v-if="title" class="sh" @touchstart.passive="dragStart" @touchmove.passive="dragMove" @touchend="dragEnd" @touchcancel="dragCancel">
          <h2>{{ title }}</h2>
          <slot name="actions">
            <button class="btn" :disabled="!dismissible" @click="close">Готово</button>
          </slot>
        </header>
        <div class="body"><slot /></div>
      </section>
    </div>
    </Transition>
  </Teleport>
</template>

<script setup>
// Лист снизу на телефоне и всплывающая карточка на компьютере, как в iOS/macOS.
import { nextTick, ref, watch } from 'vue'

const props = defineProps({ open: Boolean, title: { type: String, default: '' }, label: { type: String, default: '' },
  dismissible: { type: Boolean, default: true } })
const emit = defineEmits(['close'])
const box = ref(null)
function close() { if (props.dismissible) emit('close') }

// Телефон: потянуть лист вниз за «ручку» или заголовок — закрыть (как в iOS). Лист едет за пальцем.
let y0 = null, dy = 0
function dragStart(e) { if (!props.dismissible || innerWidth >= 900 || box.value?.scrollTop > 0) return; y0 = e.touches[0].clientY; dy = 0 }
function dragMove(e) {
  if (y0 == null || !box.value) return
  dy = Math.max(0, e.touches[0].clientY - y0)
  box.value.style.transition = 'none'
  box.value.style.transform = `translateY(${dy}px)`
}
function dragEnd() {
  if (y0 == null || !box.value) return
  const el = box.value
  y0 = null
  el.style.transition = 'transform .22s cubic-bezier(.2, .9, .3, 1)'
  // дотянули — уезжает вниз и закрывается (лист под v-if, при новом открытии создаётся заново — сбрасывать сдвиг не нужно)
  if (props.dismissible && dy > Math.min(140, el.offsetHeight * 0.3)) { el.style.transform = 'translateY(100%)'; close() }
  else { el.style.transform = ''; setTimeout(() => { el.style.transition = '' }, 230) }
}
function dragCancel() { if (y0 == null || !box.value) return; y0 = null; box.value.style.transition = ''; box.value.style.transform = '' }
// На компьютере карточка «вырастает» из места нажатия (плашки события), на телефоне — выезжает снизу.
const origin = ref({})
let last = null
if (typeof window !== 'undefined' && !window.__hhPointer) {
  window.__hhPointer = true
  window.addEventListener('pointerdown', (e) => { window.__hhLastPointer = { x: e.clientX, y: e.clientY, t: Date.now() } }, { capture: true, passive: true })
}
watch(() => props.open, async (v) => {
  if (!v) return
  last = window.__hhLastPointer && Date.now() - window.__hhLastPointer.t < 1500 ? window.__hhLastPointer : null
  origin.value = {}
  await nextTick()
  const el = box.value
  if (!el) return
  if (last && innerWidth >= 900) {
    const r = el.getBoundingClientRect()
    origin.value = { transformOrigin: `${Math.round(last.x - r.left)}px ${Math.round(last.y - r.top)}px`, animationName: 'grow' }
  }
  el.focus({ preventScroll: true })
})
</script>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 60; background: rgba(0, 0, 0, .32);
  backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center; padding: 24px;
  animation: fade .18s ease-out;
}
.sheet {
  width: min(460px, 100%); max-height: min(86vh, 760px); overflow: auto; outline: none;
  background: var(--surface); border-radius: 14px; box-shadow: var(--shadow-pop);
  animation: pop .2s ease-out;
}
.grabber { display: none; }
.sh { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 14px 12px 4px 20px; }
.sh h2 { margin: 0; font-size: 17px; font-weight: 600; }
.body { padding: 4px 20px 20px; }
@keyframes fade { from { opacity: 0 } }
@keyframes pop { from { transform: scale(.97); opacity: 0 } }
@keyframes up { from { transform: translateY(100%) } }
@keyframes grow { from { transform: scale(.25); opacity: 0 } 60% { opacity: 1 } }
.sh-leave-active { transition: opacity .18s ease-in; }
.sh-leave-active .sheet { transition: transform .18s ease-in, opacity .18s ease-in; }
.sh-leave-to { opacity: 0; }
.sh-leave-to .sheet { transform: scale(.97); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .backdrop, .sheet { animation: none !important; }
  .sh-leave-active, .sh-leave-active .sheet { transition: none; }
}

@media (max-width: 899px) {
  .backdrop { align-items: flex-end; padding: 0; }
  .sheet {
    width: 100%; max-height: 92vh; border-radius: 12px 12px 0 0;
    padding-bottom: env(safe-area-inset-bottom); animation: up .28s cubic-bezier(.2, .9, .3, 1);
  }
  .sh-leave-to .sheet { transform: translateY(100%); opacity: 1; }
  .sh-leave-active .sheet { transition: transform .22s cubic-bezier(.4, 0, 1, 1); }
  .grabber { display: block; width: 36px; height: 5px; border-radius: 3px; background: var(--ink-3); opacity: .5; margin: 6px auto 0; padding: 8px 0; background-clip: content-box; box-sizing: content-box; touch-action: none; }
  .body { padding: 4px 16px 24px; }
  .sh { padding-left: 16px; touch-action: none; }
}
</style>
