import { ref } from 'vue'
import type { CaptureStatus, CaptureTicket, ControlMessage } from '@/types'
import type { AyameConnection } from './useAyameConnection'
import { getJson, sendJson } from './http'

type CaptureResult = Extract<ControlMessage, { type: 'captureResult' }>

// Kazami が撮影してアップロードし終えるまでの待ち時間の上乗せ分。
// トークンの期限（既定 60 秒）を過ぎても結果が来なければ失敗とする。
const EXTRA_WAIT_MS = 5000

/**
 * Kazami に撮像を頼む。
 *
 * サーバーで使い捨てトークンを発行し、DataChannel で Kazami に渡す。
 * Kazami が撮影・アップロードを終えると captureResult が返ってくる。
 * DataChannel の結果を取りこぼしても、サーバーに状態を問い合わせて確かめる。
 */
export function useCapture(connection: AyameConnection, roomId: () => string, ttlSeconds: () => number) {
  const capturing = ref(0)
  const error = ref<string | null>(null)

  async function capture(extra: { tags?: string[]; note?: string } = {}): Promise<string> {
    error.value = null
    capturing.value += 1
    try {
      if (!connection.controlOpen.value) {
        throw new Error('カメラとの制御用の通信がつながっていません。Kazami が撮像に対応した版か確認してください。')
      }
      const ticket = await sendJson<CaptureTicket>('/api/captures', 'POST', { room_id: roomId(), ...extra })
      const result = waitForResult(ticket.capture_id, ttlSeconds() * 1000 + EXTRA_WAIT_MS)
      const sent = connection.sendControl({ type: 'capture', captureId: ticket.capture_id, token: ticket.token })
      if (!sent) throw new Error('カメラに撮像を頼めませんでした。接続を確認してください。')
      return await result
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      capturing.value -= 1
    }
  }

  function waitForResult(captureId: string, timeoutMs: number): Promise<string> {
    return new Promise((resolve, reject) => {
      const finish = (fn: () => void) => {
        window.clearTimeout(timer)
        unsubscribe()
        fn()
      }
      const unsubscribe = connection.onControlMessage((message) => {
        if (message.type !== 'captureResult' || message.captureId !== captureId) return
        const result = message as CaptureResult
        if (result.ok && result.imageId) finish(() => resolve(result.imageId!))
        else finish(() => reject(new Error(`カメラで撮像できませんでした（${result.message ?? '理由不明'}）。`)))
      })
      const timer = window.setTimeout(() => {
        unsubscribe()
        getJson<CaptureStatus>(`/api/captures/${captureId}`)
          .then((status) => {
            if (status.status === 'done' && status.image_id) resolve(status.image_id)
            else reject(new Error('カメラから画像が届きませんでした。Kazami の設定（kazayomi の URL）と通信を確認してください。'))
          })
          .catch(reject)
      }, timeoutMs)
    })
  }

  return { capturing, error, capture }
}
