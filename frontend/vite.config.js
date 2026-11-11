import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'

// Размер текста из настроек: каждый `font-size: Npx` превращается в calc(Npx * var(--fs, 1)).
// Меняется только текст — сетки и размеры блоков остаются прежними, перетаскивание и прокрутка не страдают.
const scaleFonts = {
  postcssPlugin: 'scale-font-size',
  Declaration: {
    'font-size': (decl) => {
      if (/^[\d.]+px$/.test(decl.value)) decl.value = `calc(${decl.value} * var(--fs, 1))`
    },
  },
}

export default defineConfig({
  css: { postcss: { plugins: [scaleFonts] } },
  plugins: [
    vue(),
    // Поддержка старых встроенных браузеров Android (WebView): синтаксис и недостающие функции.
    legacy({ modernTargets: ['chrome >= 64', 'safari >= 13'], modernPolyfills: true, renderLegacyChunks: false }),
  ],
  server: { proxy: { '/api': 'http://localhost:8765' } },
})
