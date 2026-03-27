import vueParser from 'vue-eslint-parser'

const sharedGlobals = {
  AbortController: 'readonly',
  Headers: 'readonly',
  Image: 'readonly',
  FormData: 'readonly',
  Request: 'readonly',
  Response: 'readonly',
  ResizeObserver: 'readonly',
  URL: 'readonly',
  URLSearchParams: 'readonly',
  alert: 'readonly',
  cancelAnimationFrame: 'readonly',
  clearInterval: 'readonly',
  clearTimeout: 'readonly',
  console: 'readonly',
  document: 'readonly',
  fetch: 'readonly',
  getSelection: 'readonly',
  localStorage: 'readonly',
  navigator: 'readonly',
  process: 'readonly',
  requestAnimationFrame: 'readonly',
  setInterval: 'readonly',
  setTimeout: 'readonly',
  WebSocket: 'readonly',
  window: 'readonly',
}

const sharedRules = {
  'no-undef': 'error',
  'no-unused-vars': 'off',
}

export default [
  {
    ignores: [
      'web/**',
      'node_modules/**',
      '.playwright-vite/**',
    ],
  },
  {
    files: [
      'src/**/*.js',
      'src/**/*.mjs',
      'tests/**/*.js',
      'tests/**/*.mjs',
    ],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: sharedGlobals,
    },
    rules: sharedRules,
  },
  {
    files: [
      'src/**/*.vue',
      'tests/**/*.vue',
    ],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parser: vueParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
      globals: sharedGlobals,
    },
    rules: sharedRules,
  },
]
