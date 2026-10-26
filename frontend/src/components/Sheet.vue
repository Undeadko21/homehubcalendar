<template>
  <Teleport to="body">
    <div v-if="open" class="backdrop" @click.self="$emit('close')" @keydown.esc="$emit('close')">
      <section ref="box" class="sheet" role="dialog" aria-modal="true" :aria-label="label" tabindex="-1">
        <div class="grabber" aria-hidden="true"></div>
        <header v-if="title" class="sh">
          <h2>{{ title }}</h2>
          <slot name="actions">
            <button class="btn" @click="$emit('close')">Готово</button>
          </slot>
        </header>
        <div class="body"><slot /></div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
// Лист снизу на телефоне и всплывающая карточка на компьютере, как в iOS/macOS.
import { nextTick, ref, watch } from 'vue'

const props = defineProps({ open: Boolean, title: { type: String, default: '' }, label: { type: String, default: '' } })
defineEmits(['close'])
const box = ref(null)
watch(() => props.open, async (v) => { if (v) { await nextTick(); box.value?.focus() } })
</script>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 60; background: rgba(0, 0, 0, .32);
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

@media (max-width: 899px) {
  .backdrop { align-items: flex-end; padding: 0; }
  .sheet {
    width: 100%; max-height: 92vh; border-radius: 12px 12px 0 0;
    padding-bottom: env(safe-area-inset-bottom); animation: up .28s cubic-bezier(.2, .9, .3, 1);
  }
  .grabber { display: block; width: 36px; height: 5px; border-radius: 3px; background: var(--ink-3); opacity: .5; margin: 6px auto 0; }
  .body { padding: 4px 16px 24px; }
  .sh { padding-left: 16px; }
}
</style>
