<template>
  <div class="library">
    <!-- 左: 期間とツリー -->
    <aside class="pane pane--left">
      <div class="pane__section">
        <div class="field-label">期間</div>
        <v-text-field v-model="baseDate" type="date" label="基準日" density="compact" />
        <v-btn-toggle v-model="days" mandatory density="compact" divided variant="outlined" class="days">
          <v-btn v-for="d in dayOptions" :key="d" :value="d">{{ d }}日</v-btn>
        </v-btn-toggle>
        <p class="meta-text">{{ formatDateKey(range.from) }} 〜 {{ formatDateKey(range.to) }}</p>
      </div>

      <div class="tree">
        <button class="tree__node" :class="{ 'tree__node--active': !treeRoom }" @click="selectTree(null, null)">
          <v-icon icon="mdi-image-multiple-outline" size="16" />
          <span class="tree__label">すべて</span>
          <span class="tree__count">{{ summaryTotal }}</span>
        </button>
        <template v-for="cam in tree" :key="cam.key">
          <button
            class="tree__node"
            :class="{ 'tree__node--active': treeRoom === cam.key && !treeDate }"
            @click="selectTree(cam.key, null)"
          >
            <v-icon
              :icon="expanded.has(cam.key) ? 'mdi-chevron-down' : 'mdi-chevron-right'"
              size="16"
              @click.stop="toggleExpand(cam.key)"
            />
            <span class="tree__label">{{ cam.name }}</span>
            <span class="tree__count">{{ cam.count }}</span>
          </button>
          <template v-if="expanded.has(cam.key)">
            <button
              v-for="date in cam.dates"
              :key="date.dateKey"
              class="tree__node tree__node--child"
              :class="{ 'tree__node--active': treeRoom === cam.key && treeDate === date.dateKey }"
              @click="selectTree(cam.key, date.dateKey)"
            >
              <span class="tree__label">{{ formatDateKey(date.dateKey) }}</span>
              <span class="tree__count">{{ date.count }}</span>
            </button>
          </template>
        </template>
        <p v-if="tree.length === 0 && !summaryLoading" class="meta-text">この期間の画像はありません</p>
      </div>
    </aside>

    <!-- 中央: 一覧 -->
    <section class="pane pane--center">
      <div class="toolbar">
        <span class="toolbar__count">
          <strong>{{ images.length }}</strong>
          <template v-if="total > images.length"> / {{ total }}</template> 枚
        </span>
        <span v-if="treeRoomName" class="chip chip--sm">
          {{ treeRoomName }}<template v-if="treeDate"> / {{ formatDateKey(treeDate) }}</template>
          <v-icon icon="mdi-close" size="12" class="chip__close" @click="selectTree(null, null)" />
        </span>
      </div>

      <!-- 選択・絞り込みの操作は 1 行にまとめる -->
      <div class="filter-bar">
        <template v-if="selection.selected.value.size > 0">
          <span class="filter-bar__count"><strong>{{ selection.selected.value.size }}</strong> 枚を選択中</span>
          <v-btn size="small" variant="text" prepend-icon="mdi-close-box-multiple-outline" @click="selection.clear()">選択解除</v-btn>
          <v-btn v-if="permissions.can_edit" size="small" variant="text" color="primary" prepend-icon="mdi-tag-multiple-outline" @click="tagDialog = true">タグ付け</v-btn>
          <v-btn v-if="permissions.can_edit" size="small" variant="text" color="primary" prepend-icon="mdi-folder-plus-outline" @click="albumDialog = true">アルバムに追加</v-btn>
          <v-btn size="small" variant="text" prepend-icon="mdi-folder-zip-outline" :loading="zipping" @click="downloadSelected">ZIP</v-btn>
          <v-btn v-if="permissions.can_edit" size="small" variant="text" color="error" prepend-icon="mdi-delete-outline" @click="askDelete">削除</v-btn>
        </template>
        <template v-else>
          <v-btn size="small" variant="text" prepend-icon="mdi-checkbox-multiple-marked-outline" :disabled="images.length === 0" @click="selection.selectAll()">全選択</v-btn>
          <span class="filter-bar__hint">Shift+クリックで範囲選択 / Ctrl・⌘+クリックで追加 / ダブルクリックで拡大</span>
        </template>
        <v-btn
          size="small"
          :prepend-icon="favoriteOnly ? 'mdi-star' : 'mdi-star-outline'"
          :variant="favoriteOnly ? 'tonal' : 'text'"
          :color="favoriteOnly ? 'warning' : undefined"
          @click="favoriteOnly = !favoriteOnly"
        >お気に入り</v-btn>
        <!-- タグはチップを押して絞り込む。複数選ぶと、いずれかのタグを持つ画像を出す -->
        <template v-if="tagItems.length > 0">
          <span class="filter-bar__label">タグ:</span>
          <v-chip
            v-for="tag in tagItems"
            :key="tag"
            size="small"
            color="secondary"
            :variant="isTagFilterActive(tag) ? 'elevated' : 'outlined'"
            :closable="isTagFilterActive(tag)"
            @click="toggleTagFilter(tag)"
            @click:close="toggleTagFilter(tag)"
          >#{{ tag }}</v-chip>
          <v-btn v-if="tagFilter.length > 0" size="small" variant="text" @click="tagFilter = []">タグクリア</v-btn>
        </template>
      </div>

      <v-alert v-if="error" type="error" closable class="mx-2" @click:close="error = null">{{ error }}</v-alert>

      <div class="grid-area">
        <ImageGrid
          ref="grid"
          :items="gridItems"
          :selected="selection.selected.value"
          :loading="loading"
          :has-more="nextOffset != null"
          empty-text="条件に合う画像はありません"
          @select="selection.click"
          @toggle="selection.toggle"
          @open="openDetail"
          @load-more="loadMore"
        >
        </ImageGrid>
      </div>
    </section>

    <ImageDetailDialog
      v-model="detailOpen"
      v-model:index="detailIndex"
      :images="images"
      @changed="onDetailChanged"
      @update:index="(i: number) => grid?.scrollToIndex(i)"
    />

    <AlbumAddDialog v-model="albumDialog" :image-ids="selectedIds" @added="notify" />

    <TagEditDialog
      v-model="tagDialog"
      :count="selection.selected.value.size"
      :suggestions="tagItems"
      :current-tags="selectedTags"
      :on-apply="applyTags"
    />

    <ConfirmDialog
      v-model="deleteOpen"
      title="画像を削除"
      confirm-text="削除"
      danger
      :busy="deleting"
      @confirm="confirmDelete"
    >
      選んだ {{ selection.selected.value.size }} 枚を削除します。元に戻せません。
      <template v-if="albumUsage > 0">このうち {{ albumUsage }} 枚はアルバムに入っています。アルバムからも外れます。</template>
    </ConfirmDialog>

    <v-snackbar v-model="snackbar" :timeout="3500" location="bottom right">{{ snackbarText }}</v-snackbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AlbumAddDialog from '@/components/AlbumAddDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ImageDetailDialog from '@/components/ImageDetailDialog.vue'
import ImageGrid from '@/components/ImageGrid.vue'
import TagEditDialog from '@/components/TagEditDialog.vue'
import { formatDateKey, inputDateToKey, keyToInputDate, toDateKey } from '@/composables/format'
import {
  batchTags,
  countAlbumUsage,
  deleteImages,
  downloadZip,
  fetchSummary,
  fetchTags,
  listImages,
} from '@/composables/imagesApi'
import { useSelection, type GridItem } from '@/composables/selection'
import { useAuth } from '@/composables/useAuth'
import { useStoredRef } from '@/composables/useStoredRef'
import { tagKey, uniqueTags } from '@/composables/tags'
import type { ImageRecord, ImageSummaryRow, TagCount, TagMode } from '@/types'

const PAGE_SIZE = 500
const dayOptions = [1, 7, 30, 90] as const

const route = useRoute()
const { permissions } = useAuth()

// ── 期間 ──────────────────────────────────────────
const baseDate = ref(keyToInputDate(toDateKey(new Date())))
const days = useStoredRef<number>('kazayomi.libraryDays', 7)
const range = computed(() => {
  const to = inputDateToKey(baseDate.value) || toDateKey(new Date())
  const end = new Date(Number(to.slice(0, 4)), Number(to.slice(4, 6)) - 1, Number(to.slice(6)))
  const start = new Date(end)
  start.setDate(end.getDate() - (days.value - 1))
  return { from: toDateKey(start), to }
})

// ── ツリー（ルーム → 日付）──────────────────────────
const summary = ref<ImageSummaryRow[]>([])
const summaryLoading = ref(false)
const expanded = ref(new Set<string>())
const treeRoom = ref<string | null>(null) // ルーム ID、または手動取り込みの 'none'
const treeDate = ref<string | null>(null)

interface TreeRoom { key: string; name: string; count: number; dates: { dateKey: string; count: number }[] }

const tree = computed<TreeRoom[]>(() => {
  const map = new Map<string, TreeRoom>()
  for (const row of summary.value) {
    const key = row.room_id ?? (row.room_name ? `name:${row.room_name}` : 'none')
    const name = row.room_name || '手動で取り込み'
    const node = map.get(key) ?? { key, name, count: 0, dates: [] }
    node.count += row.count
    const date = node.dates.find((d) => d.dateKey === row.date_key)
    if (date) date.count += row.count
    else node.dates.push({ dateKey: row.date_key, count: row.count })
    map.set(key, node)
  }
  return [...map.values()]
})
const summaryTotal = computed(() => summary.value.reduce((sum, row) => sum + row.count, 0))
const treeRoomName = computed(() => tree.value.find((c) => c.key === treeRoom.value)?.name ?? '')

function selectTree(room: string | null, date: string | null): void {
  treeRoom.value = room
  treeDate.value = date
  if (room) expanded.value = new Set([...expanded.value, room])
}

function toggleExpand(key: string): void {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

// ── 絞り込み ──────────────────────────────────────
const favoriteOnly = ref(false)
/** 絞り込みに使うタグ（tagKey の形。表記ゆれを同じものとみなす） */
const tagFilter = ref<string[]>([])
const tagCounts = ref<TagCount[]>([])
const tagItems = computed(() => tagCounts.value.map((t) => t.tag))

const isTagFilterActive = (tag: string) => tagFilter.value.includes(tagKey(tag))

function toggleTagFilter(tag: string): void {
  const key = tagKey(tag)
  tagFilter.value = isTagFilterActive(tag) ? tagFilter.value.filter((v) => v !== key) : [...tagFilter.value, key]
}

// ── 一覧 ──────────────────────────────────────────
const images = ref<ImageRecord[]>([])
const total = ref(0)
const nextOffset = ref<number | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const gridItems = computed<GridItem[]>(() => images.value.map((image) => ({ id: image.id, image })))
const selection = useSelection(() => gridItems.value)
const grid = ref<InstanceType<typeof ImageGrid> | null>(null)

// ルームを消した画像は room_id が無いので、撮像時点の表示名で分ける
function roomQuery(): { roomId: string | null; roomName: string | null } {
  const key = treeRoom.value
  if (!key) return { roomId: null, roomName: null }
  if (key.startsWith('name:')) return { roomId: 'none', roomName: key.slice(5) }
  if (key === 'none') return { roomId: 'none', roomName: '' }
  return { roomId: key, roomName: null }
}

async function load(append = false): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const res = await listImages({
      ...roomQuery(),
      dateFrom: treeDate.value ?? range.value.from,
      dateTo:   treeDate.value ?? range.value.to,
      tags:     tagFilter.value,
      favorite: favoriteOnly.value ? true : null,
      limit:    PAGE_SIZE,
      offset:   append ? images.value.length : 0,
    })
    images.value = append ? [...images.value, ...res.items] : res.items
    total.value = res.total
    nextOffset.value = res.next_offset
    selection.prune()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function loadMore(): void {
  void load(true)
}

async function loadSummary(): Promise<void> {
  summaryLoading.value = true
  try {
    summary.value = await fetchSummary(range.value.from, range.value.to)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    summaryLoading.value = false
  }
}

async function loadTags(): Promise<void> {
  try {
    tagCounts.value = await fetchTags()
  } catch {
    // タグの候補が出なくても一覧は使える
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([load(), loadSummary(), loadTags()])
}

watch(range, () => {
  treeDate.value = null
  void loadSummary()
  void load()
})
watch([treeRoom, treeDate, favoriteOnly, tagFilter], () => { void load() })

// ── 詳細 ──────────────────────────────────────────
const detailOpen = ref(false)
const detailIndex = ref(0)

function openDetail(index: number): void {
  detailIndex.value = index
  detailOpen.value = true
}

function onDetailChanged(kind: 'updated' | 'deleted', image: ImageRecord): void {
  if (kind === 'updated') {
    images.value = images.value.map((i) => (i.id === image.id ? image : i))
    void loadTags()
  } else {
    images.value = images.value.filter((i) => i.id !== image.id)
    total.value -= 1
    selection.prune()
    void loadSummary()
  }
}

// ── 一括操作 ──────────────────────────────────────
const tagDialog = ref(false)
const albumDialog = ref(false)
const zipping = ref(false)
const deleteOpen = ref(false)
const deleting = ref(false)
const albumUsage = ref(0)
const snackbar = ref(false)
const snackbarText = ref('')

const selectedIds = computed(() => [...selection.selected.value])
const selectedTags = computed(() =>
  uniqueTags(images.value.filter((i) => selection.selected.value.has(i.id)).flatMap((i) => i.tags))
    .sort((a, b) => a.localeCompare(b, 'ja')),
)

function notify(text: string): void {
  snackbarText.value = text
  snackbar.value = true
}

async function applyTags(tags: string[], mode: TagMode): Promise<void> {
  const result = await batchTags(selectedIds.value, tags, mode)
  notify(`${result.updated} 枚のタグを更新しました`)
  await Promise.all([load(), loadTags()])
}

async function downloadSelected(): Promise<void> {
  zipping.value = true
  try {
    await downloadZip(selectedIds.value)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    zipping.value = false
  }
}

async function askDelete(): Promise<void> {
  albumUsage.value = 0
  deleteOpen.value = true
  try {
    albumUsage.value = (await countAlbumUsage(selectedIds.value)).count
  } catch {
    // 件数が出なくても削除はできる
  }
}

async function confirmDelete(): Promise<void> {
  deleting.value = true
  try {
    const result = await deleteImages(selectedIds.value)
    deleteOpen.value = false
    selection.clear()
    notify(`${result.deleted} 枚を削除しました`)
    await refreshAll()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  const room = route.query.room
  if (typeof room === 'string' && room) selectTree(room, null)
  void refreshAll()
})
</script>

<style scoped>
.library {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  height: calc(100dvh - var(--app-top));
}
.pane { display: flex; flex-direction: column; min-height: 0; }
.pane--left { gap: var(--sp-3); padding: var(--sp-4) var(--sp-3); overflow-y: auto; background: var(--surface-card); }
.pane--left { border-right: 1px solid var(--border-default); }
.pane__section { display: flex; flex-direction: column; gap: var(--sp-2); }
.days { width: 100%; }
.days :deep(.v-btn) { flex: 1; min-width: 0; font-size: var(--fs-xs); }

.tree { display: flex; flex-direction: column; gap: 1px; }
.tree__node {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  width: 100%;
  padding: var(--sp-1) var(--sp-2);
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--ink-2);
  background: none;
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}
.tree__node:hover { background: var(--surface-subtle); }
.tree__node--child { padding-left: 30px; }
.tree__node--active { color: var(--text-brand); background: var(--surface-accent); font-weight: var(--fw-medium); }
.tree__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tree__count { color: var(--ink-4); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }

.pane--center { padding: var(--sp-3) var(--sp-3) 0; gap: var(--sp-2); }
.toolbar { display: flex; align-items: center; gap: var(--sp-2); padding: 0 var(--sp-1); }
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-1);
  min-height: 36px;
  max-height: 104px;
  padding: var(--sp-1);
  overflow-y: auto;
  border-bottom: 1px solid var(--border-default);
}
.filter-bar__count { padding: 0 var(--sp-1); color: var(--text-brand); font-size: var(--fs-sm); }
.filter-bar__hint { color: var(--ink-4); font-size: var(--fs-xs); white-space: nowrap; }
.filter-bar__label { margin-left: var(--sp-2); color: var(--ink-3); font-size: var(--fs-sm); }
.toolbar__count { color: var(--ink-2); font-size: var(--fs-sm); }
.chip__close { margin-left: 2px; cursor: pointer; }
.grid-area { flex: 1; min-height: 0; }
</style>
