import type { ApiError } from '@/types'
import { goToLogin } from './useAuth'

/**
 * API 呼び出しの共通処理。composable からだけ使う（コンポーネントに fetch を書かない）。
 * エラーはバックエンドが返す `{ error }` の日本語メッセージで投げ直す。
 */
export async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new Error('サーバーに接続できません。ネットワークとサーバーの状態を確認してください。')
  }
  if (res.status === 401) {
    // セッションが切れた。どの画面からでも同じくログイン画面へ戻す
    goToLogin()
    throw new Error('ログインが切れました。ログインし直してください。')
  }
  const text = await res.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }
  if (!res.ok) {
    const message = (body as ApiError | null)?.error
    throw new Error(message ?? `サーバーでエラーが起きました（HTTP ${res.status}）。`)
  }
  return body as T
}

export function getJson<T>(url: string): Promise<T> {
  return requestJson<T>(url)
}

export function sendJson<T>(url: string, method: 'POST' | 'PUT' | 'PATCH' | 'DELETE', payload?: unknown): Promise<T> {
  return requestJson<T>(url, {
    method,
    headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
    body:    payload === undefined ? undefined : JSON.stringify(payload),
  })
}

/** POST で受け取った ZIP などをファイルとして保存させる。 */
export async function downloadPost(url: string, payload: unknown, fallbackName: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    })
  } catch {
    throw new Error('サーバーに接続できません。ネットワークとサーバーの状態を確認してください。')
  }
  if (res.status === 401) {
    goToLogin()
    throw new Error('ログインが切れました。ログインし直してください。')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null) as ApiError | null
    throw new Error(body?.error ?? `ダウンロードできませんでした（HTTP ${res.status}）。`)
  }
  const blob = await res.blob()
  saveBlob(blob, fileNameFrom(res.headers.get('content-disposition')) ?? fallbackName)
}

/** GET のダウンロードはブラウザに任せる（大きな ZIP をメモリに載せないため）。 */
export function downloadGet(url: string): void {
  const a = document.createElement('a')
  a.href = url
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

function fileNameFrom(disposition: string | null): string | null {
  if (!disposition) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (encoded) return decodeURIComponent(encoded[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : null
}
