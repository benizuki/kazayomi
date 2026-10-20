import { ref, watch, type Ref } from 'vue'

/**
 * localStorage に覚えておく ref。コーデックやタイルの大きさのような、端末ごとの好みに使う。
 * 共有すべき状態には使わない（サーバーに置く）。
 * プライベートブラウズなどで localStorage が使えなくても、画面は既定値で動く。
 */
export function useStoredRef<T>(key: string, fallback: T): Ref<T> {
  const value = ref(read()) as Ref<T>

  function read(): T {
    try {
      const raw = window.localStorage.getItem(key)
      return raw == null ? fallback : (JSON.parse(raw) as T)
    } catch {
      return fallback
    }
  }

  watch(value, (next) => {
    try {
      window.localStorage.setItem(key, JSON.stringify(next))
    } catch {
      // 保存できなくても動作には影響しない
    }
  }, { deep: true })

  return value
}
