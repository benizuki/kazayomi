import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { fileURLToPath, URL } from 'node:url'
import { thirdPartyLicenses } from './scripts/third-party-licenses'

export default defineConfig({
  plugins: [
    vue(),
    // 使ったコンポーネントだけを自動で取り込む。手書きの import が不要になる。
    vuetify({ autoImport: true }),
    // 依存パッケージのライセンス文を dist/licenses/ に書き出す（画面のメニューから開ける）
    thirdPartyLicenses({ projectLicense: fileURLToPath(new URL('../LICENSE', import.meta.url)) }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 開発時は Vite(5173) と backend(8080) が別 Origin になるのでプロキシする。
    // セッション Cookie を同じ Origin で扱うため、ログインまわりも中継する。
    // backend にパスを足したら、ここにも足すこと。
    proxy: {
      // ws: true はシグナリングの中継（/api/channels/{id}/signaling）のため
      '/api':     { target: 'http://localhost:8080', ws: true },
      '/auth':    'http://localhost:8080',
      '/login':   'http://localhost:8080',
      '/logout':  'http://localhost:8080',
      '/healthz': 'http://localhost:8080',
    },
  },
  build: {
    // backend が ../frontend/dist を配信する前提。
    outDir: './dist',
    emptyOutDir: true,
  },
})
