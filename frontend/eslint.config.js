// Узкий набор правил: только то, что ломает работу и что сборка пропускает молча
// (v0.19: newEvent без импорта в App.vue; повторяющийся ключ в api.js). Стиль кода не проверяем.
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'public/**'] },
  ...vue.configs['flat/essential'],
  {
    files: ['src/**/*.{js,vue}', 'tests/**/*.js', '*.config.js'],
    languageOptions: { ecmaVersion: 'latest', sourceType: 'module', globals: { ...globals.browser, ...globals.node } },
    rules: {
      'no-undef': 'error',            // имя без импорта / опечатка
      'no-dupe-keys': 'error',        // { changes: …, changes: … } — второй затирает первый
      'no-dupe-class-members': 'error',
      'no-duplicate-case': 'error',
      'no-unreachable': 'error',
      'no-self-assign': 'error',
      'no-const-assign': 'error',
      'no-import-assign': 'error',
      'vue/no-undef-components': 'off',
      'vue/multi-word-component-names': 'off',
      'vue/no-mutating-props': 'error',
      'vue/no-dupe-keys': 'error',     // одно имя в props/setup/computed
      'vue/require-v-for-key': 'off',
      'vue/valid-v-for': 'error',
      'vue/no-unused-components': 'off',
      'vue/no-reserved-component-names': 'off',
    },
  },
]
