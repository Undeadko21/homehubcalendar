import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'

export default defineConfig({
  plugins: [
    vue(),
    // Поддержка старых встроенных браузеров Android (WebView): синтаксис и недостающие функции.
    legacy({ modernTargets: ['chrome >= 64', 'safari >= 13'], modernPolyfills: true, renderLegacyChunks: false }),
  ],
  server: { proxy: { '/api': 'http://localhost:8765' } },
})
