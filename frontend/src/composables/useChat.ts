import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { randomId, type AyameConnection } from './useAyameConnection'
import { useAuth } from './useAuth'

/** 1 通の長さの上限（Kazami でも同じだけに切る） */
export const CHAT_MAX_LENGTH = 200
/** 映像の上に送った分を残しておく時間（Kazami の画面に出ている時間と同じ） */
const VISIBLE_MS = 30_000

export interface SentChat {
  id:     string
  text:   string
  sentAt: Date
  /** Kazami の画面に出た（chatRead が返ってきた） */
  read:   boolean
}

/**
 * Kazami への文字のメッセージ。騒がしい現場で声が届かないときに、Kazami の画面へ吹き出しで出す。
 * 送った分は、既読が付くまで映像の上に並べておく。
 */
export function useChat(connection: AyameConnection) {
  const { user } = useAuth()
  const draft = ref('')
  const sent = ref<SentChat[]>([])
  const now = ref(Date.now())
  const timer = window.setInterval(() => { now.value = Date.now() }, 5_000)

  /** つながっていて、チャットに対応した Kazami のときだけ使える */
  const available = computed(() =>
    connection.status.value === 'connected' && connection.controlOpen.value
    && (connection.peerInfo.value?.capabilities?.includes('chat') ?? false))

  /** 使えないときの理由（入力欄に出す）。使えるときは null */
  const unavailableReason = computed(() => {
    if (connection.status.value !== 'connected') return 'Kazami につながると、文字で伝えられます'
    if (!connection.controlOpen.value) return 'Kazami との制御用の通信を待っています'
    if (!available.value) return 'この Kazami はメッセージに対応していません。Kazami を新しい版にしてください'
    return null
  })

  /** 映像の上に出しておく分（新しいものが下） */
  const visible = computed(() => sent.value.filter((message) => now.value - message.sentAt.getTime() < VISIBLE_MS))

  const stop = connection.onControlMessage((message) => {
    if (message.type !== 'chatRead') return
    const target = sent.value.find((item) => item.id === message.id)
    if (target) target.read = true
  })

  // 切れたら、映像の上の吹き出しも片付ける（別の Kazami につながり直すこともあるため）
  watch(available, (ok) => { if (!ok) sent.value = [] })

  function send(): boolean {
    const text = draft.value.trim().slice(0, CHAT_MAX_LENGTH)
    if (!text || !available.value) return false
    const id = randomId()
    const ok = connection.sendControl({ type: 'chat', id, text, from: user.value?.name ?? '' })
    if (!ok) return false
    sent.value = [...sent.value.slice(-9), { id, text, sentAt: new Date(), read: false }]
    now.value = Date.now()
    draft.value = ''
    return true
  }

  onBeforeUnmount(() => {
    stop()
    window.clearInterval(timer)
  })

  return { draft, visible, available, unavailableReason, send }
}
