<template>
  <form class="login" @submit.prevent="submit">
    <h1>Домашний календарь</h1>
    <label for="pin" class="muted">Введите PIN-код</label>
    <input id="pin" v-model="pin" type="password" inputmode="numeric" autocomplete="current-password" autofocus />
    <p v-if="error" class="err">{{ error }}</p>
    <button class="btn filled" :disabled="!pin">Войти</button>
  </form>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../lib/api'
import { reload } from '../lib/store'

const pin = ref('')
const error = ref('')
async function submit() {
  error.value = ''
  try {
    await api.login(pin.value)
    await reload()
  } catch (e) {
    error.value = 'PIN не подошёл. Проверьте и попробуйте ещё раз.'
  }
}
</script>

<style scoped>
.login { max-width: 320px; margin: 18vh auto; padding: 24px; display: flex; flex-direction: column; gap: 10px; }
h1 { font-size: 24px; margin: 0 0 8px; }
input { padding: 10px 12px; border: 0; border-radius: var(--radius-m); background: var(--fill); font-size: 20px; letter-spacing: .3em; }
.err { color: var(--now); margin: 0; }
</style>
