import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'src/test/**',
      'e2e/**',
    ],
  },

  // Vue 3 essential rules
  ...pluginVue.configs['flat/essential'],

  // Custom rules
  {
    files: ['src/**/*.{js,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    rules: {
      // ── Catch the two bugs we just fixed ──────────────────────
      // 'ref' was used but not imported → ReferenceError at runtime
      'no-undef': 'error',
      // 'AppSelect, AppSelect' duplicated in the same import specifier
      'no-duplicate-imports': 'error',
      // Catch unused variables (e.g. import but never used)
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],

      // ── Vue-specific ──────────────────────────────────────────
      'vue/no-unused-components': 'warn',
      'vue/component-name-in-template-casing': ['warn', 'PascalCase'],
      // single-word names like Skeleton, Dashboard are idiomatic in UI libs and route views
      'vue/multi-word-component-names': 'warn',
    },
  },
]
