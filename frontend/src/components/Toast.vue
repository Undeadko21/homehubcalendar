<template>
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="state.toast" class="toast" role="status" aria-live="polite">
        <span class="txt">{{ state.toast.text }}</span>
        <button v-if="state.toast.undo" class="undo" :disabled="state.toast.busy" @click="runToastUndo">
          {{ state.toast.busy ? '…' : 'Отменить' }}
        </button>
        <button class="x" aria-label="Скрыть" @click="hideToast">×</button>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
// Плашка внизу экрана после действия: что сделано и «Отменить» на несколько секунд.
import { state, hideToast, runToastUndo } from '../lib/store'
</script>

<style scoped>
.toast {
  position: fixed; left: 50%; transform: translateX(-50%); z-index: 90;
  bottom: calc(24px + env(safe-area-inset-bottom)); max-width: min(560px, calc(100vw - 24px));
  display: flex; align-items: center; gap: 4px; padding: 6px 6px 6px 16px; border-radius: 14px;
  background: #1c1c1e; color: #fff; font-size: 15px; box-shadow: 0 8px 28px rgba(0, 0, 0, .28);
}
.txt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.undo { border: 0; background: none; color: #ff9f0a; font: inherit; font-weight: 700; padding: 8px 10px; border-radius: 8px; flex: none; }
.undo:active { background: rgba(255, 255, 255, .12); }
.x { border: 0; background: none; color: rgba(255, 255, 255, .6); font-size: 20px; line-height: 1; padding: 6px 10px; flex: none; }
@media (max-width: 899px) { .toast { bottom: calc(var(--tabbar) + 12px + env(safe-area-inset-bottom)); } }
.toast-enter-active, .toast-leave-active { transition: opacity .2s, transform .2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 12px); }
:root[data-theme='dark'] .toast { background: #3a3a3c; }
@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) .toast { background: #3a3a3c; } }
</style>
