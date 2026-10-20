<template>
  <div ref="scroller" class="grid-scroller" @scroll.passive="onScroll">
    <div v-if="items.length === 0 && !loading" class="empty-state">
      <v-icon icon="mdi-image-off-outline" size="40" />
      <p>{{ emptyText }}</p>
    </div>
    <div class="grid-spacer" :style="{ height: `${totalHeight}px` }">
      <div
        v-for="row in visibleRows"
        :key="row.index"
        class="grid-row"
        :style="{ transform: `translateY(${row.index * rowHeight}px)`, gridTemplateColumns: `repeat(${columns}, 1fr)`, height: `${rowHeight - GAP}px` }"
      >
        <div
          v-for="cell in row.cells"
          :key="cell.item.id"
          class="cell"
          :class="{ 'cell--selected': selected.has(cell.item.id) }"
          @click="emit('select', cell.index, $event)"
          @dblclick="emit('open', cell.index)"
          @mouseenter="hovered = cell.item.id"
          @mouseleave="hovered = null"
        >
          <div class="cell__thumb">
            <img :src="thumbUrl(cell.item.image.id)" :alt="cell.item.image.captured_at" loading="lazy" draggable="false">
            <div class="cell__badges">
              <slot name="badges" :item="cell.item" />
              <v-icon v-if="cell.item.image.favorite" icon="mdi-star" size="16" class="cell__fav" />
            </div>
            <!-- タグは画像の上に重ねて出す（3 つまで、それ以上は +N） -->
            <div v-if="cell.item.image.tags.length" class="cell__tags">
              <span v-for="tag in cell.item.image.tags.slice(0, 3)" :key="tag" class="cell__tag">#{{ tag }}</span>
              <span v-if="cell.item.image.tags.length > 3" class="cell__tag">+{{ cell.item.image.tags.length - 3 }}</span>
            </div>
            <!-- 選択は右上の丸（いつも出す）。拡大はマウスを載せたときだけ右下に出す -->
            <button
              class="cell__check"
              :aria-label="selected.has(cell.item.id) ? '選択を外す' : '選択する'"
              @click.stop="emit('toggle', cell.index, $event)"
            >
              <v-icon :icon="selected.has(cell.item.id) ? 'mdi-checkbox-marked-circle' : 'mdi-checkbox-blank-circle-outline'" size="22" />
            </button>
            <button v-if="hovered === cell.item.id" class="cell__open" aria-label="大きく表示" @click.stop="emit('open', cell.index)">
              <v-icon icon="mdi-magnify-plus-outline" size="18" />
            </button>
          </div>
          <div class="cell__caption">
            <span class="cell__time">{{ caption(cell.item) }}</span>
            <slot name="caption" :item="cell.item" />
          </div>
        </div>
      </div>
    </div>
    <div v-if="hasMore || loading" class="grid-more">
      <v-btn variant="outlined" :loading="loading" @click="emit('loadMore')">さらに読み込む</v-btn>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { thumbUrl } from '@/composables/imagesApi'
import type { GridItem } from '@/composables/selection'

/**
 * サムネイルの仮想スクロール一覧。
 *
 * 数千枚を並べても重くならないよう、見えている行の前後だけを DOM に載せる。
 * 行の高さを計算で決めるため、カードの大きさは列幅から一律に決まる（画像の縦横比で変えない）。
 * 操作ボタンはホバー中のカードにだけ描く。
 */

const props = withDefaults(defineProps<{
  items:      GridItem[]
  selected:   Set<string>
  loading?:   boolean
  hasMore?:   boolean
  emptyText?: string
  /** カードの目安の幅（px）。列数はここから決める */
  cellSize?:  number
}>(), { loading: false, hasMore: false, emptyText: '画像がありません', cellSize: 168 })

const emit = defineEmits<{
  select:   [index: number, event: MouseEvent]
  toggle:   [index: number, event: MouseEvent]
  open:     [index: number]
  loadMore: []
}>()

const GAP = 8
const CAPTION = 22
const OVERSCAN_ROWS = 3

const scroller = ref<HTMLElement | null>(null)
const width = ref(0)
const height = ref(0)
const scrollTop = ref(0)
const hovered = ref<string | null>(null)

const columns = computed(() => Math.max(1, Math.floor((width.value + GAP) / (props.cellSize + GAP))))
const cellWidth = computed(() => (width.value - GAP * (columns.value - 1)) / columns.value)
// 正方形のサムネイル＋撮像時刻の行＋行間
const rowHeight = computed(() => Math.max(1, Math.round(cellWidth.value + CAPTION + GAP)))
const rowCount = computed(() => Math.ceil(props.items.length / columns.value))
const totalHeight = computed(() => rowCount.value * rowHeight.value)

const visibleRows = computed(() => {
  const first = Math.max(0, Math.floor(scrollTop.value / rowHeight.value) - OVERSCAN_ROWS)
  const last = Math.min(rowCount.value - 1, Math.ceil((scrollTop.value + height.value) / rowHeight.value) + OVERSCAN_ROWS)
  const rows = []
  for (let r = first; r <= last; r++) {
    const cells = []
    for (let c = 0; c < columns.value; c++) {
      const index = r * columns.value + c
      if (index >= props.items.length) break
      cells.push({ index, item: props.items[index] })
    }
    rows.push({ index: r, cells })
  }
  return rows
})

function caption(item: GridItem): string {
  const d = new Date(item.image.captured_at)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function onScroll(): void {
  scrollTop.value = scroller.value?.scrollTop ?? 0
}

let observer: ResizeObserver | null = null
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    width.value = entry.contentRect.width
    height.value = entry.contentRect.height
  })
  if (scroller.value) observer.observe(scroller.value)
})
onBeforeUnmount(() => observer?.disconnect())

/** 指定の位置が見えるようにスクロールする（詳細表示で移動したときなど）。 */
function scrollToIndex(index: number): void {
  const el = scroller.value
  if (!el) return
  const top = Math.floor(index / columns.value) * rowHeight.value
  if (top < el.scrollTop || top + rowHeight.value > el.scrollTop + el.clientHeight) {
    el.scrollTop = Math.max(0, top - rowHeight.value)
  }
}

// 絞り込みを変えて中身が入れ替わったら先頭へ戻す
watch(() => props.items[0]?.id, () => {
  if (scroller.value) scroller.value.scrollTop = 0
  scrollTop.value = 0
})

defineExpose({ scrollToIndex })
</script>

<style scoped>
.grid-scroller {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: var(--sp-1);
  user-select: none;
}
.grid-spacer { position: relative; }
.grid-row {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: grid;
  gap: 8px;
}
.cell {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.cell__thumb {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  border: 2px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
}
.cell--selected .cell__thumb { border-color: var(--surface-accent-solid); }
.cell--selected .cell__thumb::after {
  content: '';
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--surface-accent-solid) 18%, transparent);
  pointer-events: none;
}
.cell__thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
.cell__badges {
  position: absolute;
  left: var(--sp-1);
  bottom: var(--sp-1);
  display: flex;
  align-items: center;
  gap: 2px;
}
.cell__fav { color: var(--surface-warn-solid); filter: drop-shadow(0 0 2px rgb(0 0 0 / 0.6)); }
.cell__tags {
  position: absolute;
  top: var(--sp-1);
  left: var(--sp-1);
  right: 32px;
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  pointer-events: none;
}
.cell__tag {
  max-width: 100%;
  padding: 1px 4px;
  overflow: hidden;
  border-radius: 3px;
  color: #fff;
  background: color-mix(in srgb, var(--surface-accent-solid) 88%, transparent);
  font-size: var(--fs-2xs);
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell__check {
  position: absolute;
  top: 2px;
  right: 2px;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  color: #fff;
  background: none;
  filter: drop-shadow(0 1px 2px rgb(0 0 0 / 0.6));
  cursor: pointer;
}
.cell--selected .cell__check { color: var(--surface-accent-solid); filter: drop-shadow(0 0 2px rgb(255 255 255 / 0.9)); }
.cell__open {
  position: absolute;
  right: var(--sp-1);
  bottom: var(--sp-1);
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--ink-1);
  background: color-mix(in srgb, var(--surface-card) 85%, transparent);
  cursor: pointer;
}
.cell__caption {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  height: 22px;
  padding: 0 2px;
  overflow: hidden;
  color: var(--ink-3);
  font-size: var(--fs-2xs);
  white-space: nowrap;
}
.cell__time { font-variant-numeric: tabular-nums; }
.grid-more { display: flex; justify-content: center; padding: var(--sp-4); }
</style>
