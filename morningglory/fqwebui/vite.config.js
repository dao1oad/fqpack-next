import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd(), '')
  const pageChunkMatchers = [
    {
      chunkName: 'page-runtime-observability',
      matches: [
        '/src/views/RuntimeObservability.vue',
        '/src/views/runtimeObservability.mjs',
        '/src/views/runtimeObservabilityQueries.mjs',
        '/src/views/runtimeObservabilitySelection.mjs',
        '/src/views/runtimeObservabilityFilters.mjs'
      ]
    },
    {
      chunkName: 'page-daily-screening',
      matches: [
        '/src/views/DailyScreening.vue',
        '/src/views/dailyScreeningPage.mjs',
        '/src/views/dailyScreeningFilters.mjs',
        '/src/views/dailyScreeningWorkspace.mjs',
        '/src/views/dailyScreeningDetail.mjs'
      ]
    },
    {
      chunkName: 'page-kline-slim',
      matches: [
        '/src/views/KlineSlim.vue',
        '/src/views/js/kline-slim.js',
        '/src/views/klineSlimSidebar.mjs',
        '/src/views/klineSlimPageState.mjs'
      ]
    }
  ]

  const resolveManualChunk = (id) => {
    if (id.includes('node_modules')) {
      if (id.includes('element-plus')) return 'vendor-element-plus'
      if (id.includes('echarts')) return 'vendor-echarts'
      if (id.includes('@tanstack/vue-query')) return 'vendor-vue-query'
      if (id.includes('lodash')) return 'vendor-lodash'
      return 'vendor-core'
    }

    const normalizedId = id.replace(/\\/g, '/')
    const matchedChunk = pageChunkMatchers.find(({ matches }) => matches.some((segment) => normalizedId.includes(segment)))
    return matchedChunk?.chunkName
  }

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src')
      }
    },
    server: {
      port: 8089,
      open: false,
      proxy: {
        '/api': {
          target: env.VITE_API_BASE_URL || 'http://127.0.0.1:5000',
          ws: true,
          changeOrigin: true,
          // 重写路径（如果后端不需要 /api 前缀）
          rewrite: (path) => path
        }
      }
    },
    build: {
      outDir: 'web',
      sourcemap: false,
      chunkSizeWarningLimit: 1000,
      rollupOptions: {
        output: {
          manualChunks: resolveManualChunk
        }
      },
      // 生产环境移除 console
      terserOptions: {
        compress: {
          drop_console: true,
          drop_debugger: true
        }
      }
    }
  }
})
