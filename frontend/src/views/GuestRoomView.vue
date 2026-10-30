<template>
  <div class="single">
    <section class="stage">
      <VideoPlayer
        class="stage__player"
        :stream="conn.stream.value"
        :muted="!speakerOn"
        :placeholder="placeholder"
        :busy="isBusy"
        :pickable="canFocusRemotely"
        :pointer-color="pointer.playerColor.value"
        @pick="focusAt"
        @pointer="pointer.send"
      >
        <div class="stage__badge">
          <span class="chip chip--pill" :class="statusChipClass">{{ statusLabel }}</span>
          <span v-if="conn.stats.value?.codec" class="stage__stats">
            {{ conn.stats.value.codec }} {{ conn.stats.value.width }}×{{ conn.stats.value.height }}
            {{ conn.stats.value.fps }}fps
            <template v-if="conn.stats.value.route"> / {{ routeLabel(conn.stats.value.route) }}</template>
          </span>
        </div>
        <transition name="flash"><div v-if="flash" class="stage__flash" /></transition>
        <ChatSent :messages="chat.visible.value" />
      </VideoPlayer>
      <ChatInput :chat="chat" />
    </section>

    <aside class="side">
      <div class="side__head">
        <div class="side__title">
          <div class="section-title">あなたのルーム</div>
          <div v-if="room" class="meta-text">{{ expiryText }}</div>
        </div>
      </div>

      <v-alert v-if="error" type="error">{{ error }}</v-alert>
      <p v-if="room && !room.signaling_ready" class="tip tip--compact tip--warn">
        <v-icon icon="mdi-alert-outline" />
        <span>シグナリングサーバが設定されていないため、まだつなげません。運営者にお問い合わせください。</span>
      </p>

      <!-- 接続・音声・撮像 -->
      <div class="panel side__block">
        <div class="controls">
          <v-btn v-if="conn.status.value === 'idle'" icon color="primary" size="small" :disabled="!room" aria-label="接続する" @click="conn.connect()">
            <v-icon icon="mdi-play" />
            <v-tooltip activator="parent" location="bottom">接続する</v-tooltip>
          </v-btn>
          <v-btn v-else icon size="small" color="error" variant="tonal" aria-label="切断する" @click="conn.disconnect()">
            <v-icon icon="mdi-stop" />
            <v-tooltip activator="parent" location="bottom">切断する</v-tooltip>
          </v-btn>
          <v-btn
            icon
            size="small"
            :color="speakerOn ? 'secondary' : undefined"
            :variant="speakerOn ? 'flat' : 'outlined'"
            :aria-label="speakerOn ? 'スピーカーを切る' : 'スピーカーを入れる'"
            @click="speakerOn = !speakerOn"
          >
            <v-icon :icon="speakerOn ? 'mdi-volume-high' : 'mdi-volume-off'" />
            <v-tooltip activator="parent" location="bottom">{{ speakerOn ? 'スピーカーを切る' : 'スピーカーを入れる' }}</v-tooltip>
          </v-btn>
          <v-btn
            icon
            size="small"
            :color="conn.micOn.value ? 'secondary' : undefined"
            :variant="conn.micOn.value ? 'flat' : 'outlined'"
            :disabled="!canTalk"
            :aria-label="conn.micOn.value ? 'マイクを切る' : 'マイクを入れる'"
            @click="conn.setMic(!conn.micOn.value)"
          >
            <v-icon :icon="conn.micOn.value ? 'mdi-microphone' : 'mdi-microphone-off'" />
            <v-tooltip activator="parent" location="bottom">{{ conn.micOn.value ? 'マイクを切る' : 'マイクを入れる' }}</v-tooltip>
          </v-btn>
          <!-- レーザーポインター。映像の上をドラッグすると、Kazami の画面の同じ位置に出る -->
          <v-btn
            icon
            size="small"
            :color="pointer.on.value ? 'error' : undefined"
            :variant="pointer.on.value ? 'flat' : 'outlined'"
            :disabled="!pointer.available.value"
            :aria-label="pointer.on.value ? 'ポインターを止める' : 'ポインターを使う'"
            :aria-pressed="pointer.on.value"
            @click="pointer.toggle()"
          >
            <v-icon icon="mdi-laser-pointer" />
            <v-tooltip activator="parent" location="bottom">{{ pointer.on.value ? 'ポインターを止める' : 'ポインター（映像をドラッグして Kazami の画面に指し示す）' }}</v-tooltip>
          </v-btn>
          <v-spacer />
          <!-- 撮像した画像は、サーバに預けずにこのブラウザへダウンロードする -->
          <v-btn icon color="primary" :loading="capturer.capturing.value" :disabled="!conn.controlOpen.value" aria-label="撮像してダウンロード" @click="capture">
            <v-icon icon="mdi-camera-iris" />
            <v-tooltip activator="parent" location="bottom">撮像してダウンロード</v-tooltip>
          </v-btn>
        </div>
        <p class="side__status">
          {{ conn.statusText.value }}
          <template v-if="conn.peerInfo.value"> ・ {{ conn.peerInfo.value.deviceName ?? conn.peerInfo.value.app }}</template>
        </p>
        <p class="meta-text">撮像した画像はこのブラウザにダウンロードされます。サーバには保存されません。</p>
        <p v-if="conn.micError.value" class="tip tip--compact tip--danger">
          <v-icon icon="mdi-alert-outline" />
          <span>{{ conn.micError.value }}</span>
        </p>
        <p v-if="capturer.error.value" class="tip tip--compact tip--danger">
          <v-icon icon="mdi-alert-outline" />
          <span>{{ capturer.error.value }}</span>
        </p>
      </div>

      <!-- Kazami の登録。まだ登録していないときは開いておく -->
      <div class="panel side__block">
        <button type="button" class="fold" :aria-expanded="qrOpen" @click="toggleQr">
          <v-icon icon="mdi-qrcode" size="18" />
          <span class="field-label fold__title">Kazami をつなぐ</span>
          <span v-if="room?.device" class="chip chip--sm chip--brand">登録済み</span>
          <v-spacer />
          <v-icon :icon="qrOpen ? 'mdi-chevron-up' : 'mdi-chevron-down'" size="18" />
        </button>
        <template v-if="qrOpen">
          <ol class="steps">
            <li>Kazami の 設定 › 端末登録 を開く</li>
            <li>下の QR コードを読み取る</li>
            <li>登録すると、Kazami がこのルームに自動でつながります</li>
          </ol>
          <div class="qr">
            <img v-if="qrImage" :src="qrImage" alt="Kazami の登録用 QR コード" class="qr__image">
            <v-progress-circular v-else-if="issuing" indeterminate color="primary" />
          </div>
          <p v-if="enrollment" class="meta-text qr__meta">
            <template v-if="remaining > 0">あと {{ Math.floor(remaining / 60) }} 分 {{ remaining % 60 }} 秒有効（1 回限り）</template>
            <template v-else>期限が切れました</template>
          </p>
          <p v-if="justEnrolled" class="tip tip--compact">
            <v-icon icon="mdi-check-circle-outline" />
            <span>Kazami を登録しました。まもなくつながります。</span>
          </p>
          <p v-if="room?.device && !justEnrolled" class="meta-text">ほかの端末で読み取ると、いまの Kazami に代わってその端末がつながります。</p>
          <div class="row">
            <v-btn size="small" variant="outlined" prepend-icon="mdi-refresh" :loading="issuing" @click="issue">発行し直す</v-btn>
            <v-spacer />
            <v-btn size="small" variant="text" @click="showText = !showText">QR の中身</v-btn>
          </div>
          <template v-if="showText">
            <p class="meta-text">シミュレータなど、QR を読めないときは、Kazami の端末登録の画面にこれを貼り付けます。</p>
            <code class="qr__text">{{ qrText }}</code>
            <v-btn size="small" variant="text" prepend-icon="mdi-content-copy" @click="copyText">コピー</v-btn>
          </template>
          <p v-if="qrError" class="tip tip--compact tip--danger">{{ qrError }}</p>
        </template>
      </div>

      <!-- 再開コード。ログアウトしたあとや、別のブラウザ・端末からこのルームに戻るときに使う -->
      <div v-if="room?.resume_code" class="panel side__block">
        <div class="row">
          <v-icon icon="mdi-key-outline" size="18" />
          <span class="field-label">再開コード</span>
          <v-spacer />
          <v-btn
            :icon="showCode ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
            size="x-small"
            variant="text"
            :aria-label="showCode ? 'コードを隠す' : 'コードを表示'"
            @click="showCode = !showCode"
          />
          <v-btn icon="mdi-content-copy" size="x-small" variant="text" aria-label="コードをコピー" @click="copyCode" />
        </div>
        <code class="resume-code">{{ showCode ? room.resume_code : '••••-••••-••••' }}</code>
        <p class="meta-text">ログアウトしたあとや、別のブラウザから戻るときに、ログイン画面の「再開コードで戻る」に入れます。ほかの人には教えないでください。</p>
      </div>

      <!-- カメラの調整（倍率・フォーカス・色合い・露出） -->
      <CameraControlPanel :connection="conn" />

      <div class="side__end">
        <v-btn variant="text" color="error" size="small" prepend-icon="mdi-close-circle-outline" :disabled="!room" @click="endOpen = true">ルームを終了</v-btn>
        <span class="meta-text"><a href="/terms" target="_blank" rel="noopener">利用規約</a> ・ <a href="/privacy" target="_blank" rel="noopener">プライバシーポリシー</a></span>
      </div>
    </aside>

    <ConfirmDialog v-model="endOpen" title="ルームを終了" confirm-text="終了する" danger :busy="ending" @confirm="endRoom">
      このルームと、登録した Kazami の情報を消します。続けて使うときは新しいルームができるので、Kazami で QR を読み取り直してください。
    </ConfirmDialog>

    <v-snackbar v-model="snackbar" :timeout="2500" location="bottom right">{{ snackbarText }}</v-snackbar>
  </div>
</template>

<script setup lang="ts">
/**
 * ゲストの、自分の一時的なルーム。ゲストとしてログインするとでき、ここから Kazami を登録して映像を見る。
 * ルームと Kazami の登録は、最後に使ってから一定時間（既定 24 時間）で消える。
 */
import QRCode from 'qrcode'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import CameraControlPanel from '@/components/CameraControlPanel.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ChatInput from '@/components/ChatInput.vue'
import ChatSent from '@/components/ChatSent.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { copyToClipboard } from '@/composables/clipboard'
import { formatDateTime } from '@/composables/format'
import { routeLabel, useAyameConnection } from '@/composables/useAyameConnection'
import { useDirectCapture } from '@/composables/useDirectCapture'
import { useChat } from '@/composables/useChat'
import { usePointer } from '@/composables/usePointer'
import { issueGuestEnrollment, issueGuestTicket, guestSignalingUrl, useGuestRoom } from '@/composables/useGuestRoom'
import type { GuestEnrollment } from '@/types'

const { room, error, load, end } = useGuestRoom()

const conn = useAyameConnection({
  signalingUrl: guestSignalingUrl,
  roomId:       () => room.value?.ayame_room_id ?? '',
  signalingKey: issueGuestTicket,
  codec:        () => '',
  audio:        true,
})
const capturer = useDirectCapture(conn)
const pointer = usePointer(conn)
const chat = useChat(conn)

const speakerOn = ref(false)
const canTalk = computed(() => conn.status.value === 'connected' && conn.remoteHasAudio.value)
const isBusy = computed(() => ['connecting', 'negotiating', 'reconnecting'].includes(conn.status.value))
const statusLabel = computed(() => ({
  idle: '未接続', connecting: '接続中', waiting: '待機中', negotiating: '接続中',
  connected: '受信中', reconnecting: '再接続待ち', rejected: '接続できません',
}[conn.status.value]))
const statusChipClass = computed(() => ({
  'chip--brand':  conn.status.value === 'connected',
  'chip--warn':   ['waiting', 'reconnecting', 'connecting', 'negotiating'].includes(conn.status.value),
  'chip--danger': conn.status.value === 'rejected',
}))
const placeholder = computed(() => (room.value && !room.value.device
  ? '右の QR コードを Kazami で読み取ると、ここに映像が出ます'
  : conn.statusText.value))
const expiryText = computed(() => {
  if (!room.value) return ''
  const hours = Math.round(room.value.ttl_seconds / 3600)
  return `使わないまま ${hours} 時間たつと消えます（いまは ${formatDateTime(room.value.expires_at)} まで）`
})

// ── 遠隔のフォーカス ─────────────────────────────
const canFocusRemotely = computed(() =>
  conn.status.value === 'connected' && conn.controlOpen.value
  && (conn.peerInfo.value?.capabilities?.includes('camera') ?? false))

function focusAt(point: { x: number, y: number }): void {
  conn.sendControl({ type: 'cameraSet', focusPoint: point })
}

// ── 撮像（ブラウザにダウンロード）─────────────────
const flash = ref(false)
const snackbar = ref(false)
const snackbarText = ref('')

async function capture(): Promise<void> {
  flash.value = true
  window.setTimeout(() => { flash.value = false }, 180)
  try {
    const name = await capturer.capture()
    snackbarText.value = `${name} をダウンロードしました`
    snackbar.value = true
  } catch {
    // capturer.error に理由が入っている
  }
}

// ── Kazami の登録 QR ─────────────────────────────
const qrOpen = ref(false)
const enrollment = ref<GuestEnrollment | null>(null)
const qrImage = ref('')
const qrError = ref<string | null>(null)
const issuing = ref(false)
const showText = ref(false)
const justEnrolled = ref(false)
const now = ref(Date.now())
let clock: number | undefined
let poll: number | undefined

// 全部入りの登録 QR と同じ形（v / api / token / name）。Kazami から見た手順は変わらない
const qrText = computed(() => (enrollment.value
  ? JSON.stringify({ v: 1, api: enrollment.value.api.replace(/\/$/, ''), token: enrollment.value.token, name: enrollment.value.name })
  : ''))
const remaining = computed(() => (enrollment.value ? Math.max(0, Math.round((Date.parse(enrollment.value.expires_at) - now.value) / 1000)) : 0))

watch(qrText, async (text) => {
  qrImage.value = text ? await QRCode.toDataURL(text, { errorCorrectionLevel: 'M', margin: 2, width: 280 }) : ''
})

async function issue(): Promise<void> {
  issuing.value = true
  qrError.value = null
  justEnrolled.value = false
  try {
    enrollment.value = await issueGuestEnrollment()
    startPolling()
  } catch (e) {
    qrError.value = (e as Error).message
  } finally {
    issuing.value = false
  }
}

/** QR を出している間は、読み取られたかを数秒おきに確かめる */
function startPolling(): void {
  window.clearInterval(poll)
  const before = room.value?.device?.enrolled_at ?? ''
  poll = window.setInterval(async () => {
    if (remaining.value <= 0) {
      window.clearInterval(poll)
      return
    }
    await load()
    if (room.value?.device && room.value.device.enrolled_at !== before) {
      window.clearInterval(poll)
      justEnrolled.value = true
      // Kazami がつながってくるのを待ち受ける
      if (conn.status.value === 'idle') conn.connect()
    }
  }, 3000)
}

function toggleQr(): void {
  qrOpen.value = !qrOpen.value
  if (qrOpen.value && !enrollment.value) void issue()
  if (!qrOpen.value) window.clearInterval(poll)
}

// ── 再開コード ──────────────────────────────────
// 人に見られないよう、ふだんは隠しておく
const showCode = ref(false)

async function copyCode(): Promise<void> {
  const copied = await copyToClipboard(room.value?.resume_code ?? '')
  if (!copied) showCode.value = true
  snackbarText.value = copied ? '再開コードをコピーしました' : 'コピーできませんでした。表示したコードを書き写してください'
  snackbar.value = true
}

async function copyText(): Promise<void> {
  snackbarText.value = await copyToClipboard(qrText.value) ? 'QR の中身をコピーしました' : 'コピーできませんでした。選んでコピーしてください'
  snackbar.value = true
}

// ── ルームの終了 ────────────────────────────────
const endOpen = ref(false)
const ending = ref(false)

async function endRoom(): Promise<void> {
  ending.value = true
  try {
    conn.disconnect()
    await end()
    endOpen.value = false
    enrollment.value = null
    // 新しいルームを作り、登録の QR を出す
    await start()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    ending.value = false
  }
}

async function start(): Promise<void> {
  await load()
  if (!room.value) return
  // 画面を開いた目的は映像を見ることなので、すぐにつなぐ（Kazami が来るまで待ち受ける）
  conn.connect()
  if (!room.value.device) {
    qrOpen.value = true
    await issue()
  }
}

onMounted(() => {
  clock = window.setInterval(() => { now.value = Date.now() }, 1000)
  void start()
})

onBeforeUnmount(() => {
  window.clearInterval(clock)
  window.clearInterval(poll)
  conn.disconnect()
})
</script>

<style scoped>
.single {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--sp-4);
  height: calc(100dvh - var(--app-top));
  padding: var(--sp-4);
}
.stage { display: flex; flex-direction: column; gap: var(--sp-2); min-height: 0; }
.stage__player { flex: 1 1 0; min-height: 0; height: auto; }
.stage__badge { position: absolute; top: var(--sp-3); left: var(--sp-3); display: flex; align-items: center; gap: var(--sp-2); }
.stage__stats {
  padding: 2px var(--sp-2);
  border-radius: var(--radius-sm);
  color: var(--text-on-inverse);
  background: color-mix(in srgb, var(--surface-inverse-deep) 70%, transparent);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}
.stage__flash { position: absolute; inset: 0; background: white; opacity: 0.6; pointer-events: none; }
.flash-leave-active { transition: opacity 0.18s ease-out; }
.flash-leave-to { opacity: 0; }

.side { display: flex; flex-direction: column; gap: var(--sp-3); min-height: 0; overflow-y: auto; }
.side__head { display: flex; align-items: center; gap: var(--sp-2); }
.side__title { min-width: 0; }
.side__block { display: flex; flex-direction: column; gap: var(--sp-2); }
.side__status { margin: 0; color: var(--ink-2); font-size: var(--fs-sm); }
.side__block .meta-text { margin: 0; }
.side__end { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); margin-top: auto; }
.side__end a { color: inherit; }
.controls { display: flex; align-items: center; gap: var(--sp-2); }
.row { display: flex; align-items: center; gap: var(--sp-2); }

.fold { display: flex; align-items: center; gap: var(--sp-2); width: 100%; padding: 0; border: 0; background: none; color: var(--ink-3); text-align: left; cursor: pointer; }
.fold:hover .field-label { color: var(--ink-1); }
.fold__title { white-space: nowrap; }
.steps { margin: 0; padding-left: 1.3em; color: var(--ink-2); font-size: var(--fs-sm); line-height: 1.8; }
.qr { display: grid; place-items: center; min-height: 200px; padding: var(--sp-2); border-radius: var(--radius-md); background: #fff; }
.qr__image { width: 100%; max-width: 240px; height: auto; image-rendering: pixelated; }
.qr__meta { text-align: center; }
.resume-code {
  display: block;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--ink-1);
  font-family: var(--font-mono);
  font-size: var(--fs-md);
  letter-spacing: 0.08em;
  text-align: center;
}
.qr__text {
  display: block;
  padding: var(--sp-2);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .single { grid-template-columns: 1fr; height: auto; }
  .stage__player { flex: none; aspect-ratio: 16 / 9; }
}
</style>
