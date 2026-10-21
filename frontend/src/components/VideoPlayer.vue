<template>
  <div class="player" :class="{ 'player--empty': !stream }">
    <video ref="videoRef" class="player__video" autoplay playsinline :muted="muted" @dblclick="onDoubleClick" />
    <!-- レーザーポインター。ドラッグした軌跡を描き、少しずつ消す（Kazami の画面にも同じ位置に出る） -->
    <canvas
      v-show="pointerColor"
      ref="canvasRef"
      class="player__pointer"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    />
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
  /** レーザーポインターの色（"#RRGGBB"）。渡すとポインターを使える（ドラッグで指し示す）。null なら使わない */
  pointerColor?: string | null
}>(), { muted: true, placeholder: '映像がありません', busy: false, pickable: false, pointerColor: null })

const emit = defineEmits<{
  /** ダブルクリックした位置。映像の幅・高さに対する割合（0〜1、左上が原点） */
  pick: [point: { x: number, y: number }]
  /** ポインターでドラッグした位置（pick と同じ割合）。間引いて送る */
  pointer: [point: { x: number, y: number }]
}>()

const videoRef = ref<HTMLVideoElement | null>(null)
const mark = ref<{ left: number, top: number, key: number } | null>(null)
let markTimer: number | undefined

/** 映像は object-fit: contain なので、余白を除いた映像の中の範囲（要素の左上からの位置と大きさ） */
function contentBox(): { box: DOMRect, left: number, top: number, width: number, height: number } | null {
  const video = videoRef.value
  if (!video || !video.videoWidth || !video.videoHeight) return null
  const box = video.getBoundingClientRect()
  const scale = Math.min(box.width / video.videoWidth, box.height / video.videoHeight)
  const width = video.videoWidth * scale
  const height = video.videoHeight * scale
  return { box, left: (box.width - width) / 2, top: (box.height - height) / 2, width, height }
}

/** 画面の位置を、映像に対する割合（0〜1）にする。映像の外（余白）なら null */
function toVideoPoint(clientX: number, clientY: number): { x: number, y: number, localX: number, localY: number } | null {
  const content = contentBox()
  if (!content) return null
  const localX = clientX - content.box.left
  const localY = clientY - content.box.top
  const x = (localX - content.left) / content.width
  const y = (localY - content.top) / content.height
  if (x < 0 || x > 1 || y < 0 || y > 1) return null
  return { x, y, localX, localY }
}

function onDoubleClick(event: MouseEvent): void {
  if (!props.pickable || props.pointerColor) return
  const point = toVideoPoint(event.clientX, event.clientY)
  if (!point) return
  const { x, y, localX, localY } = point
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

// ── レーザーポインター ───────────────────────────
// 点は映像に対する割合で持ち、描くときに今の表示の位置へ直す（画面の大きさが変わってもずれない）。
// 1 秒で消える（Kazami の画面と同じ）
const POINTER_LIFETIME_MS = 1000
const POINTER_SEND_INTERVAL_MS = 30
const canvasRef = ref<HTMLCanvasElement | null>(null)
const trail: { x: number, y: number, at: number }[] = []
let dragging = false
let lastSent = 0
let frame: number | undefined

function onPointerDown(event: PointerEvent): void {
  if (!props.pointerColor) return
  dragging = true
  try {
    // 映像の外へはみ出しても追い続ける（できない環境では、そのまま映像の中だけで追う）
    ;(event.target as HTMLElement).setPointerCapture(event.pointerId)
  } catch {
    // 何もしない
  }
  addPoint(event, true)
}

function onPointerMove(event: PointerEvent): void {
  if (dragging) addPoint(event, false)
}

function onPointerUp(): void {
  dragging = false
}

function addPoint(event: PointerEvent, force: boolean): void {
  const point = toVideoPoint(event.clientX, event.clientY)
  if (!point) return
  const now = performance.now()
  trail.push({ x: point.x, y: point.y, at: now })
  // 送りすぎると DataChannel が詰まるので間引く（描くのは全部）
  if (force || now - lastSent >= POINTER_SEND_INTERVAL_MS) {
    lastSent = now
    emit('pointer', { x: point.x, y: point.y })
  }
  if (frame === undefined) frame = requestAnimationFrame(draw)
}

function draw(): void {
  frame = undefined
  const canvas = canvasRef.value
  const content = contentBox()
  if (!canvas || !content) return
  const ratio = window.devicePixelRatio || 1
  const width = Math.round(content.box.width * ratio)
  const height = Math.round(content.box.height * ratio)
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width
    canvas.height = height
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  ctx.clearRect(0, 0, content.box.width, content.box.height)
  const now = performance.now()
  while (trail.length && now - trail[0].at > POINTER_LIFETIME_MS) trail.shift()
  for (const point of trail) {
    const alpha = 1 - (now - point.at) / POINTER_LIFETIME_MS
    const x = content.left + point.x * content.width
    const y = content.top + point.y * content.height
    ctx.globalAlpha = alpha * 0.8
    ctx.fillStyle = '#ffffff'
    ctx.beginPath()
    ctx.arc(x, y, 7, 0, Math.PI * 2)
    ctx.fill()
    ctx.globalAlpha = alpha
    ctx.fillStyle = props.pointerColor ?? '#ea4335'
    ctx.beginPath()
    ctx.arc(x, y, 5, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1
  // 残っている点があるあいだだけ描き続ける
  if (trail.length) frame = requestAnimationFrame(draw)
}

watch(() => props.pointerColor, (color) => {
  if (color) return
  dragging = false
  trail.length = 0
  if (frame === undefined) frame = requestAnimationFrame(draw)
})

watch(() => props.stream, attach)
watch(() => props.muted, attach)
onMounted(attach)
onBeforeUnmount(() => {
  window.clearTimeout(markTimer)
  if (frame !== undefined) cancelAnimationFrame(frame)
})

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
/* ポインターを使っている間は、映像の上の操作をすべて受ける（指でなぞってもスクロールしない） */
.player__pointer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  cursor: crosshair;
  touch-action: none;
}
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
