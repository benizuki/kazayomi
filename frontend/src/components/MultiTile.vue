<template>
  <div class="tile" :class="{ 'tile--max': maximized }">
    <VideoPlayer :stream="conn.stream.value" :placeholder="conn.statusText.value" :busy="isBusy">
      <div class="tile__bar">
        <span class="chip chip--sm chip--pill" :class="chipClass">{{ statusLabel }}</span>
        <span class="tile__name">{{ room.name }}</span>
        <span v-if="conn.stats.value?.codec" class="tile__stats">{{ conn.stats.value.width }}×{{ conn.stats.value.height }} {{ conn.stats.value.fps }}fps</span>
        <v-spacer />
        <v-btn
          icon="mdi-camera-iris"
          size="x-small"
          variant="flat"
          :loading="capturer.capturing.value > 0"
          :disabled="!conn.controlOpen.value"
          aria-label="撮像"
          @click="capture"
        />
        <v-btn
          :icon="conn.status.value === 'idle' ? 'mdi-play' : 'mdi-stop'"
          size="x-small"
          variant="flat"
          :aria-label="conn.status.value === 'idle' ? '接続' : '切断'"
          @click="conn.status.value === 'idle' ? conn.connect() : conn.disconnect()"
        />
        <v-btn :icon="maximized ? 'mdi-fullscreen-exit' : 'mdi-fullscreen'" size="x-small" variant="flat" :aria-label="maximized ? '元に戻す' : '最大化'" @click="emit('maximize')" />
        <v-btn icon="mdi-open-in-new" size="x-small" variant="flat" aria-label="単一ビューで開く" @click="emit('openSingle')" />
      </div>
      <transition name="flash"><div v-if="flash" class="tile__flash" /></transition>
      <div v-if="message" class="tile__message" :class="{ 'tile__message--error': messageIsError }">{{ message }}</div>
    </VideoPlayer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { relaySignalingUrl, useAyameConnection } from '@/composables/useAyameConnection'
import { useCapture } from '@/composables/useCapture'
import { issueRoomTicket } from '@/composables/useRooms'
import type { AppConfig, Room } from '@/types'

const props = defineProps<{
  room:    Room
  config:    AppConfig
  codec:     string
  maximized: boolean
}>()
const emit = defineEmits<{ maximize: []; openSingle: [] }>()

// マルチビューは見張る用途なので映像だけ受ける（台数ぶんの音声が混ざると聞き取れない）
const conn = useAyameConnection({
  signalingUrl: () => relaySignalingUrl(props.room.id),
  roomId:       () => props.room.ayame_room_id,
  signalingKey: () => issueRoomTicket(props.room.id),
  codec:        () => props.codec,
  audio:        false,
})
const capturer = useCapture(conn, () => props.room.id, () => props.config.capture_token_ttl_seconds)

const isBusy = computed(() => ['connecting', 'negotiating', 'reconnecting'].includes(conn.status.value))
const statusLabel = computed(() => ({
  idle: '未接続', connecting: '接続中', waiting: '待機中', negotiating: '接続中',
  connected: '受信中', reconnecting: '再接続待ち', rejected: '接続できません',
}[conn.status.value]))
const chipClass = computed(() => ({
  'chip--brand':  conn.status.value === 'connected',
  'chip--warn':   ['waiting', 'reconnecting', 'connecting', 'negotiating'].includes(conn.status.value),
  'chip--danger': conn.status.value === 'rejected',
}))

const flash = ref(false)
const message = ref('')
const messageIsError = ref(false)
let messageTimer: number | undefined

function show(text: string, isError: boolean): void {
  message.value = text
  messageIsError.value = isError
  window.clearTimeout(messageTimer)
  messageTimer = window.setTimeout(() => { message.value = '' }, isError ? 6000 : 2000)
}

async function capture(): Promise<void> {
  flash.value = true
  window.setTimeout(() => { flash.value = false }, 180)
  try {
    await capturer.capture()
    show('保存しました', false)
  } catch (e) {
    show((e as Error).message, true)
  }
}

onMounted(() => conn.connect())
</script>

<style scoped>
.tile { position: relative; aspect-ratio: 16 / 9; min-width: 0; }
.tile--max { aspect-ratio: auto; height: 100%; }
.tile__bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  padding: var(--sp-1) var(--sp-2);
  background: linear-gradient(to bottom, rgb(0 0 0 / 0.55), transparent);
}
.tile__bar :deep(.v-btn) { color: var(--text-on-inverse); background: rgb(255 255 255 / 0.12); }
.tile__name { overflow: hidden; color: var(--text-on-inverse); font-size: var(--fs-sm); font-weight: var(--fw-bold); text-overflow: ellipsis; white-space: nowrap; }
.tile__stats { color: var(--text-on-inverse-muted); font-family: var(--font-mono); font-size: var(--fs-2xs); }
.tile__flash { position: absolute; inset: 0; background: white; opacity: 0.6; pointer-events: none; }
.flash-leave-active { transition: opacity 0.18s ease-out; }
.flash-leave-to { opacity: 0; }
.tile__message {
  position: absolute;
  left: var(--sp-2);
  right: var(--sp-2);
  bottom: var(--sp-2);
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--radius-sm);
  color: var(--text-brand);
  background: var(--surface-accent);
  font-size: var(--fs-xs);
}
.tile__message--error { color: var(--text-danger); background: var(--surface-danger); }
</style>
