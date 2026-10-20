import { computed, ref, readonly } from 'vue'

/**
 * ライト / ダークの切り替え。
 *
 * 3 状態にしているのが肝。「システムに従う」を既定にしておくと、
 * 端末をダークにしている人は何も操作しなくても最初からダークで開ける。
 * light / dark の 2 状態だけだと、必ずどちらかを押させることになる。
 */
export type ThemeMode = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'theme-mode'

// モジュールスコープの ref。useThemeMode() をどこから何度呼んでも同じ状態を指す。
// テーマは画面ごとに別々だと困るため。
const mode = ref<ThemeMode>(readStoredMode())

// OS 側の設定。ユーザーが OS のテーマを切り替えたら追随させる。
const query = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-color-scheme: dark)')
  : null
const systemIsDark = ref(query?.matches ?? false)
query?.addEventListener('change', (e) => { systemIsDark.value = e.matches })

/** 実際に適用されるテーマ。Vuetify のテーマ名としてもそのまま使う。 */
const effectiveTheme = computed<'light' | 'dark'>(() =>
  mode.value === 'system' ? (systemIsDark.value ? 'dark' : 'light') : mode.value,
)

function readStoredMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // プライベートモードなどで localStorage が読めないことがある。
    // 既定に倒すだけでよいので握りつぶす。
  }
  return 'system'
}

function applyMode(next: ThemeMode): void {
  const root = document.documentElement
  if (next === 'system') {
    // 属性を消すと tokens.css の color-scheme: light dark が効き、OS に従う。
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', next)
  }
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // 保存できなくても表示は切り替わる。次回開いたときに既定へ戻るだけ。
  }
}

export function useThemeMode() {
  function setMode(next: ThemeMode): void {
    mode.value = next
    applyMode(next)
  }

  /** system → light → dark → system の順に回す。ボタン 1 つで 3 状態を選べる。 */
  function cycleMode(): void {
    const order: ThemeMode[] = ['system', 'light', 'dark']
    setMode(order[(order.indexOf(mode.value) + 1) % order.length])
  }

  return {
    mode: readonly(mode),
    effectiveTheme,
    setMode,
    cycleMode,
  }
}
