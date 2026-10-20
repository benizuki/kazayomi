<template>
  <!-- 画像の描画領域（object-fit: contain の余白を除いた部分）にぴったり重ねる -->
  <canvas
    ref="canvasRef"
    class="marker-canvas"
    :class="{ 'marker-canvas--editing': editing, 'marker-canvas--drawing': drawingPolygon }"
    :style="{ visibility: visible ? 'visible' : 'hidden' }"
  />
</template>

<script setup lang="ts">
/**
 * 画像に重ねて描く図形（楕円・多角形・吹き出し）。
 *
 * - 図形は画像の幅・高さに対する割合（0〜1）で受け取り・返す。画像を拡大・縮小しても位置がずれない
 * - 編集中（editing）だけ、マウスで選ぶ・動かす・大きさを変える・回す（Shift を押しながらドラッグ）ができる
 * - 多角形は、クリックで頂点を足し、最初の頂点の近くをクリックすると閉じる
 * - 吹き出しは、本体をドラッグで動かし、しっぽの先（青い丸）をドラッグで指す先を変える。文字は呼び出し元が setCalloutText で入れる
 *
 * paper.js は既定では 1 つの描画先を全体で共有するので、PaperScope を自前で持つ。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import paper from 'paper'
import type { Marker } from '@/types'

/** 呼び出し元に知らせる選択の状態 */
export interface MarkerSelection {
  item:    boolean
  vertex:  boolean
  drawing: boolean
  /** 選んでいるのが吹き出しなら、その文字。吹き出しでなければ null */
  calloutText: string | null
}

const props = defineProps<{
  /** 図形を重ねる画像 */
  image:    HTMLImageElement | null
  markers:  Marker[]
  editing:  boolean
  visible:  boolean
}>()
const emit = defineEmits<{
  /** 選択の状態（ボタンの押せる・押せないに使う） */
  selection: [state: MarkerSelection]
}>()

const STROKE = '#ff3b30'
const HANDLE = '#2979ff'
// 図形の内側を押しても掴めるよう、見えないほど薄く塗っておく（塗りが無いと線の上しか当たらない）
const FILL = 'rgba(255, 59, 48, 0.01)'
// 吹き出しは文字を読ませるので、白地にして画像の上でも読めるようにする
const CALLOUT_FILL = 'rgba(255, 255, 255, 0.92)'
const CALLOUT_TEXT = '#3a2e24'

const canvasRef = ref<HTMLCanvasElement | null>(null)
const drawingPolygon = ref(false)

let scope: paper.PaperScope | null = null
let selectedItem: paper.Item | null = null
let selectedVertex: paper.Segment | null = null
let resizeHandle: paper.Path | null = null
let vertexHandles: paper.Path[] = []
let anchorHandle: paper.Path | null = null
let currentPolygon: paper.Path | null = null
let previewLine: paper.Path | null = null
let resizeObserver: ResizeObserver | null = null

function notify(): void {
  const calloutText = selectedItem?.data.type === 'callout' ? String(selectedItem.data.text ?? '') : null
  emit('selection', { item: !!selectedItem, vertex: !!selectedVertex, drawing: drawingPolygon.value, calloutText })
}

// ── 大きさ合わせ ──────────────────────────────────

/** 画像の中で、実際に画素が描かれている領域（画像の枠の左上からの位置）。object-fit: contain の余白を除く */
function contentRect(img: HTMLImageElement): { left: number, top: number, width: number, height: number } | null {
  const box = img.getBoundingClientRect()
  const parent = img.offsetParent?.getBoundingClientRect()
  if (!parent || !img.naturalWidth || !img.naturalHeight || !box.width || !box.height) return null
  const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight)
  const width = img.naturalWidth * scale
  const height = img.naturalHeight * scale
  return {
    left: box.left - parent.left + (box.width - width) / 2,
    top: box.top - parent.top + (box.height - height) / 2,
    width,
    height,
  }
}

/** 画像の大きさが変わったら、キャンバスを合わせて描き直す（編集中の図形は割合にしてから戻す） */
function fit(): void {
  const canvas = canvasRef.value
  const img = props.image
  if (!canvas || !img) return
  const rect = contentRect(img)
  if (!rect) return
  const shapes = scope && props.editing ? collect() : props.markers
  canvas.style.left = `${rect.left}px`
  canvas.style.top = `${rect.top}px`
  canvas.style.width = `${rect.width}px`
  canvas.style.height = `${rect.height}px`
  if (!scope) {
    scope = new paper.PaperScope()
    scope.setup(canvas)
    setupTool()
  }
  scope.activate()
  scope.view.viewSize = new scope.Size(rect.width, rect.height)
  draw(shapes)
}

function observe(img: HTMLImageElement | null): void {
  resizeObserver?.disconnect()
  if (!img) return
  resizeObserver = new ResizeObserver(() => fit())
  resizeObserver.observe(img)
  if (img.complete) fit()
  else img.addEventListener('load', fit, { once: true })
}

// ── 描く・集める ──────────────────────────────────

function size(): { w: number, h: number } {
  const s = scope!.view.viewSize
  return { w: s.width, h: s.height }
}

function clearAll(): void {
  if (!scope) return
  scope.activate()
  scope.project.activeLayer.removeChildren()
  selectedItem = null
  selectedVertex = null
  resizeHandle = null
  vertexHandles = []
  anchorHandle = null
  currentPolygon = null
  previewLine = null
  drawingPolygon.value = false
}

function draw(shapes: Marker[]): void {
  if (!scope) return
  clearAll()
  const { w, h } = size()
  for (const shape of shapes) {
    if (shape.type === 'ellipse') {
      const ellipse = new scope.Path.Ellipse({
        center: [w * shape.x, h * shape.y],
        size: [w * shape.width, h * shape.height],
        strokeColor: STROKE,
        strokeWidth: 2,
        fillColor: FILL,
      })
      ellipse.applyMatrix = false
      ellipse.rotation = shape.rotation ?? 0
      ellipse.data.type = 'ellipse'
    } else if (shape.type === 'polygon') {
      const path = new scope.Path({
        segments: shape.points.map((p) => [w * p.x, h * p.y]),
        closed: true,
        strokeColor: STROKE,
        strokeWidth: 2,
        fillColor: FILL,
      })
      path.data.type = 'polygon'
    } else if (shape.type === 'callout') {
      makeCallout([w * shape.x, h * shape.y], [w * shape.bx, h * shape.by], shape.text)
    }
  }
  notify()
}

// ── 吹き出し ──────────────────────────────────────
// 吹き出しは Group にし、data に「指す先（anchor）・中心（center）・文字（text）」を持たせる。
// 形はこの 3 つから毎回作り直す（文字の長さで大きさが変わり、しっぽの向きも変わるため）。

/** 文字の大きさは画像の表示幅に合わせる（拡大・縮小しても、画像に対する大きさが変わらないように） */
function calloutFontSize(): number {
  return Math.min(22, Math.max(10, size().w * 0.014))
}

function makeCallout(anchor: [number, number], center: [number, number], text: string): paper.Group {
  const group = new scope!.Group()
  group.data = { type: 'callout', anchor, center, text }
  buildCallout(group)
  return group
}

function buildCallout(group: paper.Group): void {
  const s = scope!
  const { anchor, center, text } = group.data as { anchor: [number, number], center: [number, number], text: string }
  group.removeChildren()
  const fontSize = calloutFontSize()
  const label = new s.PointText({
    content: text || ' ',
    fontSize,
    fontFamily: 'DM Sans, Noto Sans JP, Hiragino Kaku Gothic ProN, sans-serif',
    fillColor: CALLOUT_TEXT,
    justification: 'center',
    insert: false,
  })
  label.position = new s.Point(center)
  const box = label.bounds.expand(fontSize * 1.2, fontSize * 0.8)
  const rect = new s.Path.Rectangle({ rectangle: box, radius: fontSize * 0.5, insert: false })
  let bubble: paper.PathItem = rect
  const tip = new s.Point(anchor)
  // しっぽは、本体の中心から指す先へ向かう三角形を本体に足して作る（指す先が本体の中にあれば付けない）
  if (!box.contains(tip)) {
    const half = Math.min(box.width, box.height) * 0.22
    const side = tip.subtract(box.center).normalize().rotate(90, new s.Point(0, 0)).multiply(half)
    const tail = new s.Path({ segments: [box.center.add(side), tip, box.center.subtract(side)], closed: true, insert: false })
    bubble = rect.unite(tail, { insert: false })
  }
  bubble.strokeColor = new s.Color(STROKE)
  bubble.strokeWidth = 2
  bubble.fillColor = new s.Color(CALLOUT_FILL)
  group.addChildren([bubble, label])
  if (group === selectedItem) group.selected = true
}

/** 当たった部品から、それを含む図形（一番上の層の子）を返す。吹き出しは Group の中の部品に当たるため */
function shapeOf(item: paper.Item | undefined): paper.Item | undefined {
  let current = item
  while (current?.parent && current.parent !== scope?.project.activeLayer) current = current.parent
  return current
}

// 割合は小数 5 桁あれば足りる（4000px の画像でも 0.04px）
const round = (v: number) => Number(v.toFixed(5))

/** 描いてある図形を、画像に対する割合にして返す */
function collect(): Marker[] {
  if (!scope) return []
  const { w, h } = size()
  const shapes: Marker[] = []
  for (const item of scope.project.activeLayer.children) {
    if (item.data?.type === 'ellipse') {
      // 回す前の幅・高さを測るため、複製を回転 0 に戻す
      const clone = item.clone({ insert: false }) as paper.Path
      clone.rotate(-clone.rotation, clone.position)
      shapes.push({
        type: 'ellipse',
        x: round(item.position.x / w),
        y: round(item.position.y / h),
        width: round(clone.bounds.width / w),
        height: round(clone.bounds.height / h),
        rotation: round(((item.rotation % 360) + 360) % 360),
      })
      clone.remove()
    } else if (item.data?.type === 'polygon') {
      const path = item as paper.Path
      shapes.push({ type: 'polygon', points: path.segments.map((s) => ({ x: round(s.point.x / w), y: round(s.point.y / h) })) })
    } else if (item.data?.type === 'callout') {
      const { anchor, center, text } = item.data as { anchor: [number, number], center: [number, number], text: string }
      shapes.push({
        type: 'callout',
        x: round(anchor[0] / w),
        y: round(anchor[1] / h),
        bx: round(center[0] / w),
        by: round(center[1] / h),
        text: text.trim(),
      })
    }
  }
  return shapes
}

// ── 選択とハンドル ────────────────────────────────

function removeHandles(): void {
  resizeHandle?.remove()
  resizeHandle = null
  vertexHandles.forEach((handle) => handle.remove())
  vertexHandles = []
  anchorHandle?.remove()
  anchorHandle = null
}

function select(item: paper.Item | null): void {
  if (selectedItem && selectedItem !== item) selectedItem.selected = false
  selectedItem = item
  selectedVertex = null
  if (item) item.selected = true
  updateHandles()
}

function updateHandles(): void {
  removeHandles()
  if (!scope || !selectedItem) {
    notify()
    return
  }
  if (selectedItem.data.type === 'ellipse') {
    // 右下の丸をドラッグして大きさを変える
    resizeHandle = new scope.Path.Circle({ center: selectedItem.bounds.bottomRight, radius: 6, fillColor: HANDLE, strokeColor: 'white', strokeWidth: 1 })
    resizeHandle.data.type = 'resizeHandle'
  } else if (selectedItem.data.type === 'callout') {
    // しっぽの先の丸をドラッグして、指す先を変える
    anchorHandle = new scope.Path.Circle({ center: selectedItem.data.anchor, radius: 6, fillColor: HANDLE, strokeColor: 'white', strokeWidth: 1 })
    anchorHandle.data.type = 'anchorHandle'
  } else {
    for (const segment of (selectedItem as paper.Path).segments) {
      const handle = new scope.Path.Circle({
        center: segment.point,
        radius: 5,
        fillColor: selectedVertex === segment ? STROKE : 'white',
        strokeColor: HANDLE,
        strokeWidth: 1,
      })
      handle.data.type = 'vertexHandle'
      handle.data.segment = segment
      vertexHandles.push(handle)
    }
  }
  notify()
}

function moveHandles(): void {
  if (!selectedItem) return
  if (resizeHandle) resizeHandle.position = selectedItem.bounds.bottomRight
  if (anchorHandle) {
    anchorHandle.position = new scope!.Point(selectedItem.data.anchor)
    anchorHandle.bringToFront()
  }
  if (selectedItem.data.type === 'polygon') {
    (selectedItem as paper.Path).segments.forEach((segment, index) => {
      if (vertexHandles[index]) vertexHandles[index].position = segment.point
    })
  }
}

// ── マウス ────────────────────────────────────────

function setupTool(): void {
  if (!scope) return
  const tool = new scope.Tool()
  let mode: 'none' | 'move' | 'resize' | 'rotate' | 'vertex' | 'anchor' = 'none'
  let offset: paper.Point | null = null
  let lastVector: paper.Point | null = null
  let draggingVertex: paper.Segment | null = null

  tool.onMouseDown = (event: paper.ToolEvent) => {
    if (!props.editing || !scope) return

    // 多角形を描いている途中
    if (drawingPolygon.value) {
      if (!currentPolygon) {
        currentPolygon = new scope.Path({ segments: [event.point], strokeColor: STROKE, strokeWidth: 2 })
        currentPolygon.data.type = 'polygon'
        return
      }
      // 最初の頂点の近くをクリックしたら閉じる
      if (currentPolygon.segments.length >= 3 && event.point.getDistance(currentPolygon.firstSegment.point) < 10) {
        finishPolygon()
        return
      }
      currentPolygon.add(event.point)
      previewLine?.remove()
      previewLine = null
      return
    }

    const hit = scope.project.hitTest(event.point, { fill: true, stroke: true, segments: true, tolerance: 8 })
    const item = shapeOf(hit?.item)

    if (item && item === anchorHandle) {
      mode = 'anchor'
      return
    }
    if (item?.data.type === 'vertexHandle') {
      draggingVertex = item.data.segment
      selectedVertex = draggingVertex
      mode = 'vertex'
      updateHandles()
      return
    }
    if (item && item === resizeHandle) {
      mode = 'resize'
      return
    }
    if (item && (item.data.type === 'ellipse' || item.data.type === 'polygon' || item.data.type === 'callout')) {
      if (selectedItem !== item) select(item)
      else {
        selectedVertex = null
        updateHandles()
      }
      if (item.data.type === 'callout') {
        // 吹き出しは回さない。本体を動かすと、指す先はそのままで本体だけが動く
        mode = 'move'
        offset = event.point.subtract(new scope.Point(item.data.center))
        return
      }
      if (event.modifiers.shift) {
        mode = 'rotate'
        lastVector = event.point.subtract(item.position)
      } else {
        mode = 'move'
        offset = event.point.subtract(item.position)
      }
      return
    }
    // 何もないところを押したら選択を外す
    select(null)
  }

  tool.onMouseMove = (event: paper.ToolEvent) => {
    if (!props.editing || !scope || !drawingPolygon.value || !currentPolygon) return
    previewLine?.remove()
    previewLine = new scope.Path.Line({ from: currentPolygon.lastSegment.point, to: event.point, strokeColor: STROKE, strokeWidth: 1, dashArray: [4, 4] })
  }

  tool.onMouseDrag = (event: paper.ToolEvent) => {
    if (!props.editing) return
    if (mode === 'vertex' && draggingVertex) {
      draggingVertex.point = event.point
      moveHandles()
      return
    }
    if (!selectedItem) return
    if (selectedItem.data.type === 'callout') {
      if (mode === 'anchor') {
        selectedItem.data.anchor = [event.point.x, event.point.y]
      } else if (mode === 'move' && offset) {
        const center = event.point.subtract(offset)
        selectedItem.data.center = [center.x, center.y]
      } else {
        return
      }
      buildCallout(selectedItem as paper.Group)
      moveHandles()
      return
    }
    if (mode === 'resize') {
      const topLeft = selectedItem.bounds.topLeft
      const next = event.point.subtract(topLeft)
      const sx = next.x / selectedItem.bounds.width
      const sy = next.y / selectedItem.bounds.height
      // 小さくしすぎて掴めなくならないようにする
      selectedItem.scale(sx > 0.2 ? sx : 1, sy > 0.2 ? sy : 1, topLeft)
      moveHandles()
    } else if (mode === 'rotate' && lastVector) {
      const vector = event.point.subtract(selectedItem.position)
      selectedItem.rotate(vector.angle - lastVector.angle, selectedItem.position)
      lastVector = vector
      moveHandles()
    } else if (mode === 'move' && offset) {
      selectedItem.position = event.point.subtract(offset)
      moveHandles()
    }
  }

  tool.onMouseUp = () => {
    mode = 'none'
    offset = null
    lastVector = null
    draggingVertex = null
  }
}

function finishPolygon(): void {
  previewLine?.remove()
  previewLine = null
  const polygon = currentPolygon
  currentPolygon = null
  drawingPolygon.value = false
  if (!polygon) {
    notify()
    return
  }
  if (polygon.segments.length < 3) {
    polygon.remove()
    notify()
    return
  }
  polygon.closed = true
  polygon.fillColor = new scope!.Color(FILL)
  select(polygon)
}

// ── 呼び出し元から使う操作 ────────────────────────

function addEllipse(): void {
  if (!scope) return
  scope.activate()
  finishPolygon()
  const { w, h } = size()
  const ellipse = new scope.Path.Ellipse({
    center: scope.view.center,
    size: [Math.max(24, w * 0.2), Math.max(16, h * 0.12)],
    strokeColor: STROKE,
    strokeWidth: 2,
    fillColor: FILL,
  })
  ellipse.applyMatrix = false
  ellipse.data.type = 'ellipse'
  select(ellipse)
}

/** 吹き出しを足す。本体は画像の中央、指す先はその左下 */
function addCallout(text = 'コメント'): void {
  if (!scope) return
  scope.activate()
  finishPolygon()
  const { w, h } = size()
  const center = scope.view.center
  select(makeCallout([center.x - w * 0.08, center.y + h * 0.15], [center.x, center.y], text))
}

/** 選んでいる吹き出しの文字を変える */
function setCalloutText(text: string): void {
  if (!scope || selectedItem?.data.type !== 'callout') return
  scope.activate()
  selectedItem.data.text = text
  buildCallout(selectedItem as paper.Group)
  moveHandles()
}

function startPolygon(): void {
  if (!scope) return
  scope.activate()
  select(null)
  currentPolygon = null
  drawingPolygon.value = true
  notify()
}

/** 選んだ頂点と次の頂点のあいだに、頂点を足す */
function addVertex(): void {
  if (!selectedVertex) return
  const path = selectedVertex.path
  const next = path.segments[(selectedVertex.index + 1) % path.segments.length]
  selectedVertex = path.insert(selectedVertex.index + 1, selectedVertex.point.add(next.point).divide(2))
  updateHandles()
}

function removeVertex(): void {
  if (!selectedVertex || selectedVertex.path.segments.length <= 3) return
  selectedVertex.remove()
  selectedVertex = null
  updateHandles()
}

function deleteSelected(): void {
  if (!selectedItem) return
  const item = selectedItem
  select(null)
  item.remove()
  notify()
}

/** 編集をやめたときに、受け取った図形の状態に戻す */
function reset(): void {
  if (!scope) return
  scope.activate()
  draw(props.markers)
}

defineExpose({ addEllipse, addCallout, setCalloutText, startPolygon, finishPolygon, addVertex, removeVertex, deleteSelected, collect, reset })

// ── 監視 ──────────────────────────────────────────

watch(() => props.image, (img) => observe(img))
// 保存した・別の画像に移ったときは描き直す（編集中は、触っている図形を消さない）
watch(() => props.markers, (markers) => {
  if (scope && !props.editing) {
    scope.activate()
    draw(markers)
  }
})
watch(() => props.editing, (on) => {
  if (!on && scope) {
    scope.activate()
    select(null)
    finishPolygon()
  }
})

onMounted(() => observe(props.image))
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  // 描画先とマウスの受け口を手放す（ダイアログを開き直すたびに増えないように）
  scope?.tools.forEach((tool) => tool.remove())
  scope?.project.remove()
  scope = null
})
</script>

<style scoped>
.marker-canvas {
  position: absolute;
  z-index: 1;
  pointer-events: none;
}
.marker-canvas--editing { pointer-events: auto; cursor: default; outline: 1px dashed rgb(255 59 48 / 60%); }
.marker-canvas--drawing { cursor: crosshair; }
</style>
