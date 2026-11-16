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

// Список файлов сборки для офлайн-кэша (public/sw.js): современные файлы, без запасных для старых WebView.
const precacheList = {
  name: 'precache-list',
  apply: 'build',
  generateBundle(_, bundle) {
    if (Object.keys(bundle).some((f) => f.includes('-legacy'))) return   // второй проход legacy-сборки
    const files = Object.keys(bundle).filter((f) => f.startsWith('assets/') && !f.endsWith('.map')).map((f) => '/' + f).sort()
    this.emitFile({ type: 'asset', fileName: 'precache.json', source: JSON.stringify(files) })
  },
}

export default defineConfig({
  test: { environment: 'happy-dom', include: ['tests/**/*.test.js'] },
  css: { postcss: { plugins: [scaleFonts] } },
  plugins: [
    vue(),
    precacheList,
    // Поддержка старых встроенных браузеров Android (WebView): синтаксис и недостающие функции.
    legacy({ modernTargets: ['chrome >= 64', 'safari >= 13'], modernPolyfills: true, renderLegacyChunks: false }),
  ],
  server: { proxy: { '/api': 'http://localhost:8765' } },
})
