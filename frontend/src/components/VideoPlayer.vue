<template>
  <div class="player" :class="{ 'player--empty': !stream }">
    <video ref="videoRef" class="player__video" autoplay playsinline :muted="muted" @dblclick="onDoubleClick" />
    <!-- ダブルクリックした位置の印（端末のカメラのフォーカス枠と同じ見え方） -->
    <div v-if="mark" :key="mark.key" class="player__mark" :style="{ left: `${mark.left}px`, top: `${mark.top}px` }" />
    <div v-if="!stream" class="player__placeholder">
      <v-progress-circular v-if="busy" indeterminate size="28" width="3" />
      <v-icon v-else icon="mdi-video-off-outline" size="32" />
      <span>{{ placeholder }}</span>
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  stream:       MediaStream | null
  muted?:       boolean
  placeholder?: string
  busy?:        boolean
  /** ダブルクリックで映像の上の位置を選べるようにする（フォーカス合わせ） */
  pickable?:    boolean
}>(), { muted: true, placeholder: '映像がありません', busy: false, pickable: false })

const emit = defineEmits<{
  /** ダブルクリックした位置。映像の幅・高さに対する割合（0〜1、左上が原点） */
  pick: [point: { x: number, y: number }]
}>()

const videoRef = ref<HTMLVideoElement | null>(null)
const mark = ref<{ left: number, top: number, key: number } | null>(null)
let markTimer: number | undefined

/** 映像は object-fit: contain なので、余白を除いた映像の中の位置にしてから割合にする */
function onDoubleClick(event: MouseEvent): void {
  const video = videoRef.value
  if (!props.pickable || !video || !video.videoWidth || !video.videoHeight) return
  const box = video.getBoundingClientRect()
  const scale = Math.min(box.width / video.videoWidth, box.height / video.videoHeight)
  const width = video.videoWidth * scale
  const height = video.videoHeight * scale
  const offsetX = (box.width - width) / 2
  const offsetY = (box.height - height) / 2
  const localX = event.clientX - box.left
  const localY = event.clientY - box.top
  const x = (localX - offsetX) / width
  const y = (localY - offsetY) / height
  if (x < 0 || x > 1 || y < 0 || y > 1) return
  mark.value = { left: localX, top: localY, key: Date.now() }
  window.clearTimeout(markTimer)
  markTimer = window.setTimeout(() => { mark.value = null }, 1200)
  emit('pick', { x, y })
}

function attach(): void {
  const video = videoRef.value
  if (!video) return
  if (video.srcObject !== props.stream) video.srcObject = props.stream
  // 音を出すかどうかを切り替えたときは、再生し直さないと止まったままのことがある
  if (props.stream) video.play().catch(() => { /* 自動再生の制限。ユーザー操作のあとで再試行される */ })
}

watch(() => props.stream, attach)
watch(() => props.muted, attach)
onMounted(attach)
onBeforeUnmount(() => window.clearTimeout(markTimer))

defineExpose({ video: videoRef })
</script>

<style scoped>
.player {
  position: relative;
  overflow: hidden;
  width: 100%;
  height: 100%;
  border-radius: var(--radius-md);
  background: var(--surface-inverse-deep);
}
.player__video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.player--empty .player__video { visibility: hidden; }
.player__mark {
  position: absolute;
  width: 64px;
  height: 64px;
  margin: -32px 0 0 -32px;
  border: 2px solid #ffd60a;
  pointer-events: none;
  animation: player-mark 1.2s ease-out forwards;
}
@keyframes player-mark {
  0% { transform: scale(1.4); opacity: 0; }
  15% { transform: scale(1); opacity: 1; }
  70% { opacity: 1; }
  100% { opacity: 0; }
}
.player__placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: var(--sp-2);
  color: var(--text-on-inverse-muted);
  font-size: var(--fs-sm);
  text-align: center;
  padding: var(--sp-4);
}
</style>
