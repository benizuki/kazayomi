<template>
  <div class="single">
    <section class="stage">
      <VideoPlayer
        :stream="conn.stream.value"
        :muted="!speakerOn"
        :placeholder="conn.statusText.value"
        :busy="isBusy"
        :pickable="canFocusRemotely"
        @pick="focusAt"
      >
        <div class="stage__badge">
          <span class="chip chip--pill" :class="statusChipClass">{{ statusLabel }}</span>
          <span v-if="conn.stats.value?.codec" class="stage__stats">
            {{ conn.stats.value.codec }} {{ conn.stats.value.width }}×{{ conn.stats.value.height }}
            {{ conn.stats.value.fps }}fps
            <template v-if="conn.stats.value.rttMs != null"> / RTT {{ conn.stats.value.rttMs }}ms</template>
          </span>
        </div>
        <transition name="flash"><div v-if="flash" class="stage__flash" /></transition>
      </VideoPlayer>
    </section>

    <aside class="side">
      <div class="side__head">
        <v-btn icon="mdi-arrow-left" variant="text" size="small" to="/" aria-label="カメラ一覧へ戻る" />
        <div class="side__title">
          <div class="section-title">{{ room?.name ?? '…' }}</div>
          <div class="meta-text">ルームID: {{ room?.ayame_room_id }}</div>
        </div>
      </div>

      <v-alert v-if="loadError" type="error">{{ loadError }}</v-alert>

      <!-- 接続・音声・撮像。言葉は出さずアイコンだけにし、意味はツールチップで出す -->
      <div class="panel side__block">
        <div class="controls">
          <v-btn
            v-if="conn.status.value === 'idle'"
            icon
            color="primary"
            size="small"
            :disabled="!room"
            aria-label="接続する"
            @click="connect"
          >
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
            @click="toggleMic"
          >
            <v-icon :icon="conn.micOn.value ? 'mdi-microphone' : 'mdi-microphone-off'" />
            <v-tooltip activator="parent" location="bottom">{{ conn.micOn.value ? 'マイクを切る' : 'マイクを入れる' }}</v-tooltip>
          </v-btn>

          <!-- コーデックはめったに変えないので、メニューに入れる -->
          <v-menu location="bottom">
            <template #activator="{ props: menuProps }">
              <v-btn v-bind="menuProps" icon size="small" variant="text" :disabled="conn.status.value !== 'idle'" aria-label="コーデック">
                <v-icon icon="mdi-tune-variant" />
                <v-tooltip activator="parent" location="bottom">コーデック（{{ codecLabel }}）。切断中に選べます</v-tooltip>
              </v-btn>
            </template>
            <v-list density="compact">
              <v-list-subheader>コーデック</v-list-subheader>
              <v-list-item
                v-for="item in codecItems"
                :key="item.value"
                :title="item.title"
                :active="codec === item.value"
                @click="codec = item.value"
              />
            </v-list>
          </v-menu>

          <v-spacer />
          <!-- 撮像はいちばん使うので、右端に大きめに置く -->
          <v-btn
            icon
            color="primary"
            :loading="capturer.capturing.value > 0"
            :disabled="!conn.controlOpen.value"
            aria-label="撮像する"
            @click="capture"
          >
            <v-icon icon="mdi-camera-iris" />
            <v-tooltip activator="parent" location="bottom">撮像する</v-tooltip>
          </v-btn>
        </div>

        <p class="side__status">
          {{ conn.statusText.value }}
          <template v-if="conn.peerInfo.value"> ・ {{ conn.peerInfo.value.deviceName ?? conn.peerInfo.value.app }}</template>
        </p>
        <v-text-field v-model="captureNote" label="撮像に付けるメモ" density="compact" hide-details />

        <p v-if="conn.status.value === 'connected' && !conn.remoteHasAudio.value" class="tip tip--compact">
          <v-icon icon="mdi-information-outline" />
          <span>カメラ側の音声がオフです。Kazami の設定で Audio Enable をオンにすると話せます。</span>
        </p>
        <p v-if="conn.micError.value" class="tip tip--compact tip--danger">
          <v-icon icon="mdi-alert-outline" />
          <span>{{ conn.micError.value }}</span>
        </p>
        <p v-if="conn.status.value === 'connected' && !conn.controlOpen.value" class="tip tip--compact tip--warn">
          <v-icon icon="mdi-alert-outline" />
          <span>カメラと制御用の通信がつながっていません。撮像には DataChannel に対応した Kazami が必要です。</span>
        </p>
        <p v-if="capturer.error.value" class="tip tip--compact tip--danger">
          <v-icon icon="mdi-alert-outline" />
          <span>{{ capturer.error.value }}</span>
        </p>
      </div>

      <!-- カメラの調整（倍率・フォーカス・色合い・露出） -->
      <CameraControlPanel :connection="conn" />

      <!-- 直近の撮像 -->
      <div class="side__block side__recent">
        <div class="row">
          <div class="field-label">このルームの最近の画像</div>
          <v-spacer />
          <v-btn variant="text" size="small" :to="`/library?room=${roomId}`">ライブラリで開く</v-btn>
        </div>
        <div v-if="recent.length === 0" class="meta-text">まだありません</div>
        <div class="recent">
          <button v-for="(image, index) in recent" :key="image.id" class="recent__item" @click="openDetail(index)">
            <img :src="thumbUrl(image.id)" :alt="image.captured_at" loading="lazy">
          </button>
        </div>
      </div>
    </aside>

    <ImageDetailDialog
      v-model="detailOpen"
      v-model:index="detailIndex"
      :images="recent"
      @changed="refreshRecent"
    />

    <v-snackbar v-model="snackbar" :timeout="2500" location="bottom right">{{ snackbarText }}</v-snackbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import CameraControlPanel from '@/components/CameraControlPanel.vue'
import ImageDetailDialog from '@/components/ImageDetailDialog.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { relaySignalingUrl, useAyameConnection } from '@/composables/useAyameConnection'
import { getRoom, issueRoomTicket } from '@/composables/useRooms'
import { useCapture } from '@/composables/useCapture'
import { useConfig } from '@/composables/useConfig'
import { listImages, thumbUrl } from '@/composables/imagesApi'
import { useStoredRef } from '@/composables/useStoredRef'
import type { Room, ImageRecord } from '@/types'

const route = useRoute()
const roomId = computed(() => String(route.params.roomId))

const { config, load: loadConfig } = useConfig()
const room = ref<Room | null>(null)
const loadError = ref<string | null>(null)

const codecItems = [
  { title: '指定なし', value: '' },
  { title: 'H264', value: 'H264' },
  { title: 'VP8', value: 'VP8' },
  { title: 'VP9', value: 'VP9' },
  { title: 'AV1', value: 'AV1' },
]
const codec = useStoredRef('kazayomi.codec', '')
const codecLabel = computed(() => codecItems.find((item) => item.value === codec.value)?.title ?? '指定なし')

const conn = useAyameConnection({
  signalingUrl: () => relaySignalingUrl(roomId.value),
  roomId:       () => room.value?.ayame_room_id ?? '',
  signalingKey: () => issueRoomTicket(roomId.value),
  codec:        () => codec.value,
  audio:        true,
})
const capturer = useCapture(conn, () => roomId.value, () => config.value?.capture_token_ttl_seconds ?? 60)

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

function connect(): void {
  conn.connect()
}

async function toggleMic(): Promise<void> {
  await conn.setMic(!conn.micOn.value)
}

// ── 遠隔のフォーカス ─────────────────────────────
// 映像をダブルクリックした位置に、Kazami のフォーカスと露出を合わせる（端末の画面をタップしたときと同じ）
const canFocusRemotely = computed(() =>
  conn.status.value === 'connected' && conn.controlOpen.value
  && (conn.peerInfo.value?.capabilities?.includes('camera') ?? false))

function focusAt(point: { x: number, y: number }): void {
  conn.sendControl({ type: 'cameraSet', focusPoint: point })
}

// ── 撮像 ──────────────────────────────────────────
const captureNote = ref('')
const flash = ref(false)
const snackbar = ref(false)
const snackbarText = ref('')

async function capture(): Promise<void> {
  flash.value = true
  window.setTimeout(() => { flash.value = false }, 180)
  try {
    await capturer.capture({ note: captureNote.value })
    snackbarText.value = '画像を保存しました'
    snackbar.value = true
    await refreshRecent()
  } catch {
    // capturer.error に理由が入っている
  }
}

// ── 直近の画像 ────────────────────────────────────
const recent = ref<ImageRecord[]>([])
const detailOpen = ref(false)
const detailIndex = ref(0)

async function refreshRecent(): Promise<void> {
  try {
    recent.value = (await listImages({ roomId: roomId.value, limit: 12 })).items
  } catch {
    // 一覧が出なくても映像の確認は続けられるので、ここでは止めない
  }
}

function openDetail(index: number): void {
  detailIndex.value = index
  detailOpen.value = true
}

async function load(): Promise<void> {
  conn.disconnect()
  loadError.value = null
  try {
    await loadConfig()
    room.value = await getRoom(roomId.value)
    // 画面を開いた目的は映像を見ることなので、すぐにつなぐ
    conn.connect()
  } catch (e) {
    loadError.value = (e as Error).message
  }
  void refreshRecent()
}

watch(roomId, load)
onMounted(load)
</script>

<style scoped>
.single {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--sp-4);
  height: calc(100dvh - var(--app-top));
  padding: var(--sp-4);
}
.stage { min-height: 0; }
.stage__badge {
  position: absolute;
  top: var(--sp-3);
  left: var(--sp-3);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
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

.side {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  min-height: 0;
  overflow-y: auto;
}
.side__head { display: flex; align-items: center; gap: var(--sp-2); }
.side__title { min-width: 0; }
.side__block { display: flex; flex-direction: column; gap: var(--sp-2); }
.side__status { margin: 0; color: var(--ink-2); font-size: var(--fs-sm); }
.row { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.controls { display: flex; align-items: center; gap: var(--sp-2); }

.recent {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-1);
}
.recent__item {
  overflow: hidden;
  aspect-ratio: 1;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  cursor: pointer;
}
.recent__item img { width: 100%; height: 100%; object-fit: cover; display: block; }

@media (max-width: 900px) {
  .single { grid-template-columns: 1fr; height: auto; }
  .stage { aspect-ratio: 16 / 9; }
}
</style>
