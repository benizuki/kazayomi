import { ref } from 'vue'
import type { ControlMessage } from '@/types'
import type { AyameConnection } from './useAyameConnection'

type Chunk = Extract<ControlMessage, { type: 'captureChunk' }>
type Done = Extract<ControlMessage, { type: 'captureDone' }>

// 1MB 前後の JPEG を分けて受け取るので、ゆとりを持たせる
const TIMEOUT_MS = 30_000

function randomId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, '0')).join('')
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** kazami-20261019-153012.jpg のような名前（撮った時刻、ブラウザの時刻帯） */
function fileName(capturedAt?: string): string {
  const d = capturedAt ? new Date(capturedAt) : new Date()
  return `kazami-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.jpg`
}

/**
 * ゲストのルームの撮像。画像をサーバに送らず、Kazami から DataChannel で受け取って、そのままダウンロードさせる。
 * kazayomi は画像を預からない（プライバシーポリシーにもそう書いている）。
 */
export function useDirectCapture(connection: AyameConnection) {
  const capturing = ref(false)
  const error = ref<string | null>(null)

  function capture(): Promise<string> {
    error.value = null
    if (!connection.controlOpen.value) {
      error.value = 'カメラとの制御用の通信がつながっていません。'
      return Promise.reject(new Error(error.value))
    }
    if (!connection.peerInfo.value?.capabilities?.includes('captureDirect')) {
      error.value = 'この Kazami はブラウザへの撮像に対応していません。Kazami を新しい版にしてください。'
      return Promise.reject(new Error(error.value))
    }
    capturing.value = true
    const captureId = randomId()
    const parts: string[] = []
    let received = 0

    return new Promise<string>((resolve, reject) => {
      const finish = (fn: () => void) => {
        window.clearTimeout(timer)
        unsubscribe()
        capturing.value = false
        fn()
      }
      const fail = (message: string) => finish(() => {
        error.value = message
        reject(new Error(message))
      })
      const unsubscribe = connection.onControlMessage((message) => {
        if (message.type === 'captureChunk' && message.captureId === captureId) {
          const chunk = message as Chunk
          if (parts[chunk.index] === undefined) received += 1
          parts[chunk.index] = chunk.data
          return
        }
        if (message.type !== 'captureDone' || message.captureId !== captureId) return
        const done = message as Done
        if (!done.ok) {
          fail(`カメラで撮像できませんでした（${done.message ?? '理由不明'}）。`)
          return
        }
        if (received === 0 || parts.length !== received) {
          fail('画像の一部が届きませんでした。もう一度撮像してください。')
          return
        }
        finish(() => {
          const binary = atob(parts.join(''))
          const bytes = new Uint8Array(binary.length)
          for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
          const url = URL.createObjectURL(new Blob([bytes], { type: 'image/jpeg' }))
          const name = fileName(done.capturedAt)
          const link = document.createElement('a')
          link.href = url
          link.download = name
          link.click()
          window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
          resolve(name)
        })
      })
      const timer = window.setTimeout(() => fail('カメラから画像が届きませんでした。通信の状態を確認してください。'), TIMEOUT_MS)
      if (!connection.sendControl({ type: 'captureDirect', captureId })) {
        fail('カメラに撮像を頼めませんでした。接続を確認してください。')
      }
    })
  }

  return { capturing, error, capture }
}
