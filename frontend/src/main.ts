import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import { ja } from 'vuetify/locale'
import { createRouter, createWebHistory } from 'vue-router'
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'

// トークンを先に読む。base.css がトークンを参照するので順番を入れ替えない。
import './styles/tokens.css'
import './styles/base.css'

import App from './App.vue'

// Vuetify のテーマ色は styles/tokens.css の写し。
// Vuetify は on-primary などを自前で計算するため、hex を直接渡す必要がある。
// ここと tokens.css は必ず同じ値に保つこと（片方だけ変えると、
// v-btn の色と手書き CSS の色が少しずつ違う画面ができる）。
const themeColors = {
  // Hinami・ayatori と同じ配色。主ボタンは墨の茶、タグや選択などのアクセントは苔色
  light: {
    primary:    '#4a3b2e', // = --surface-inverse（墨の茶）
    secondary:  '#4d6f45', // = --surface-accent-solid（苔色）
    surface:    '#fffdf8', // = --surface-card
    background: '#f7f2e8', // = --surface-page
    error:      '#b8504a', // = --surface-danger-solid
    warning:    '#a8602a', // = --surface-warn-solid
    info:       '#4e6fb8', // = --surface-info-solid
    success:    '#4d6f45', // = --surface-accent-solid
  },
  dark: {
    primary:    '#e0c9a6', // 暗い面の上で読める、和紙の色
    secondary:  '#9ec48f', // = --text-brand（dark）
    surface:    '#241e19', // = --surface-card
    background: '#1b1612', // = --surface-page
    error:      '#f0948a', // = --text-danger（dark）
    warning:    '#a8602a', // = --surface-warn-solid
    info:       '#5674bb', // = --surface-info-solid
    success:    '#9ec48f', // = --text-brand（dark）
  },
} as const

// コンポーネントとディレクティブは vite-plugin-vuetify の autoImport が使った分だけ取り込む
const vuetify = createVuetify({
  // 表のページ送りや「データがありません」などの既定の文言を日本語にする
  locale: { locale: 'ja', fallback: 'ja', messages: { ja } },
  theme: {
    // 起動直後の値。App.vue が useThemeMode の結果で即座に上書きするので、
    // ここを dark にしても挙動は変わらない。
    // 実際の既定は「システムに従う」（composables/useThemeMode.ts）。
    defaultTheme: 'light',
    themes: {
      light: { dark: false, colors: { ...themeColors.light } },
      dark:  { dark: true,  colors: { ...themeColors.dark } },
    },
  },

  // 部品の既定値をここで決めるのが、見た目を揃えるいちばん確実な方法。
  // 画面ごとに variant や density を書かせると、必ずばらける。
  // 個別に上書きしたくなったら、まず「本当にその画面だけ違ってよいか」を疑う。
  defaults: {
    VBtn:       { rounded: 'lg', elevation: 0, variant: 'flat' },
    VCard:      { rounded: 'lg', elevation: 0, border: true },
    VDialog:    { maxWidth: 720 },
    // ダイアログの決定ボタンを塗りつぶしにする（Vuetify の既定は文字だけで、押せるのか分かりにくい）。
    // 取り消しは各画面で variant="text" を付けている
    VCardActions: { VBtn: { variant: 'flat' } },
    // hideDetails: 'auto' を付けないと、エラーが無いときも
    // 説明文の高さが確保され、フォームの行間が画面ごとにずれる。
    VTextField: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VTextarea:  { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VSelect:    { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VAutocomplete: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VCombobox:  { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VCheckbox:  { density: 'comfortable', hideDetails: 'auto' },
    VDataTable: { density: 'comfortable', itemsPerPage: 20 },
    VChip:      { size: 'small', variant: 'tonal' },
    VAlert:     { density: 'compact', variant: 'tonal' },
    VTooltip:   { location: 'top' },
  },
})

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',                  component: () => import('./views/RoomListView.vue'), meta: { title: 'ルーム' } },
    { path: '/room',              component: () => import('./views/GuestRoomView.vue'), meta: { title: 'あなたのルーム' } },
    { path: '/view/:roomId',   component: () => import('./views/SingleView.vue'),     meta: { title: '単一ビュー' } },
    { path: '/multi',             component: () => import('./views/MultiView.vue'),      meta: { title: 'マルチビュー' } },
    { path: '/library',           component: () => import('./views/LibraryView.vue'),    meta: { title: 'ライブラリ' } },
    { path: '/albums',            component: () => import('./views/AlbumListView.vue'),  meta: { title: 'アルバム' } },
    { path: '/albums/:albumId',   component: () => import('./views/AlbumView.vue'),      meta: { title: 'アルバム' } },
    { path: '/masters/:tab?',     component: () => import('./views/MastersView.vue'),    meta: { title: 'マスター' } },
    // 未知のパスはトップに戻す。backend 側の SPA フォールバックと役割が揃う。
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${String(to.meta.title)} - kazayomi` : 'kazayomi'
})

createApp(App).use(vuetify).use(router).mount('#app')
