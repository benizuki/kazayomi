import { readonly, ref } from 'vue'
import type { AppConfig } from '@/types'
import { getJson } from './http'

// アプリ全体で 1 つ。起動時に 1 回読めば足りる。
const config = ref<AppConfig | null>(null)
let loading: Promise<AppConfig> | null = null

export function useConfig() {
  function load(): Promise<AppConfig> {
    if (config.value) return Promise.resolve(config.value)
    loading ??= getJson<AppConfig>('/api/config')
      .then((value) => { config.value = value; return value })
      .finally(() => { loading = null })
    return loading
  }

  return { config: readonly(config), load }
}
