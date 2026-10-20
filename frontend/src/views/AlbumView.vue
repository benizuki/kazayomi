<template>
  <div class="album">
    <section class="pane pane--center">
      <header class="head">
        <v-btn icon="mdi-arrow-left" variant="text" size="small" to="/albums" aria-label="アルバム一覧へ戻る" />
        <div class="head__title">
          <h1 class="section-title">{{ album?.name ?? '…' }}</h1>
          <p v-if="album?.description" class="meta-text">{{ album.description }}</p>
        </div>
        <span v-if="album" class="chip chip--sm chip--info">{{ album.group_name }}</span>
        <v-btn v-if="canEdit" icon="mdi-pencil-outline" variant="text" size="small" aria-label="名前と説明を変更" @click="editOpen = true" />
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-folder-zip-outline" :disabled="items.length === 0" :href="album ? albumExportUrl(album.id) : undefined">ZIP で書き出す</v-btn>
        <v-btn v-if="canEdit" icon="mdi-delete-outline" variant="text" size="small" color="error" aria-label="アルバムを削除" title="アルバムを削除" @click="deleteOpen = true" />
      </header>

      <!-- 選択・絞り込みの操作は 1 行にまとめる（ライブラリと同じ並び） -->
      <div class="filter-bar">
        <span class="filter-bar__total"><strong>{{ visible.length }}</strong><template v-if="visible.length !== items.length"> / {{ items.length }}</template> 枚</span>
        <template v-if="selection.selected.value.size > 0">
          <span class="filter-bar__count"><strong>{{ selection.selected.value.size }}</strong> 枚を選択中</span>
          <v-btn size="small" variant="text" prepend-icon="mdi-close-box-multiple-outline" @click="selection.clear()">選択解除</v-btn>
          <template v-if="canEdit">
            <v-btn size="small" variant="text" color="primary" prepend-icon="mdi-tag-multiple-outline" @click="tagOpen = true">タグ付け</v-btn>
            <v-btn size="small" variant="text" color="error" prepend-icon="mdi-folder-remove-outline" @click="removeOpen = true">アルバムから外す</v-btn>
          </template>
        </template>
        <template v-else>
          <v-btn size="small" variant="text" prepend-icon="mdi-checkbox-multiple-marked-outline" :disabled="visible.length === 0" @click="selection.selectAll()">全選択</v-btn>
          <span class="filter-bar__hint">Shift+クリックで範囲選択 / Ctrl・⌘+クリックで追加 / ダブルクリックで拡大</span>
        </template>
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
          :items="visible"
          :selected="selection.selected.value"
          :loading="loading"
          :empty-text="items.length === 0 ? 'このアルバムに画像がありません。ライブラリで画像を選び、「アルバムに追加」からこのアルバムを選んでください。' : '選んだタグの画像はありません'"
          @select="selection.click"
          @toggle="selection.toggle"
          @open="openDetail"
        />
      </div>
    </section>

    <ImageDetailDialog
      v-model="detailOpen"
      v-model:index="detailIndex"
      :images="visible.map((i) => i.image)"
      @changed="load"
    />

    <TagEditDialog
      v-model="tagOpen"
      :count="selection.selected.value.size"
      :suggestions="tagSuggestions"
      :current-tags="selectedTags"
      :on-apply="applyTags"
    />

    <!-- 名前と説明 -->
    <v-dialog v-model="editOpen" max-width="480">
      <v-card>
        <v-card-title class="dialog-title">アルバムの名前と説明</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="editError" type="error">{{ editError }}</v-alert>
          <v-text-field v-model="editName" label="アルバム名" />
          <v-textarea v-model="editDescription" label="説明" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :disabled="!editName.trim()" :loading="busy" @click="saveEdit">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="removeOpen" title="アルバムから外す" confirm-text="外す" :busy="busy" @confirm="removeSelected">
      選んだ {{ selection.selected.value.size }} 枚をこのアルバムから外します。画像はライブラリに残ります。
    </ConfirmDialog>
    <ConfirmDialog v-model="deleteOpen" title="アルバムを削除" confirm-text="削除" danger :busy="busy" @confirm="removeAlbum">
      「{{ album?.name }}」を削除します。画像とタグはライブラリに残ります。
    </ConfirmDialog>

    <v-snackbar v-model="snackbar" :timeout="3000" location="bottom right">{{ snackbarText }}</v-snackbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ImageDetailDialog from '@/components/ImageDetailDialog.vue'
import ImageGrid from '@/components/ImageGrid.vue'
import TagEditDialog from '@/components/TagEditDialog.vue'
import { batchTags, fetchTags } from '@/composables/imagesApi'
import { tagKey, uniqueTags } from '@/composables/tags'
import { useSelection, type GridItem } from '@/composables/selection'
import {
  albumExportUrl,
  deleteAlbum,
  getAlbum,
  listAlbumItems,
  removeAlbumItems,
  updateAlbum,
} from '@/composables/useAlbums'
import { useAuth } from '@/composables/useAuth'
import type { Album, AlbumItem, TagMode } from '@/types'

const route = useRoute()
const router = useRouter()
const albumId = computed(() => String(route.params.albumId))
const { canIn } = useAuth()

const album = ref<Album | null>(null)
// 変えられるのは、アルバムのグループで編集の権限を持っているときだけ
const canEdit = computed(() => canIn(album.value?.group_id, 'can_edit'))
const items = ref<AlbumItem[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const snackbar = ref(false)
const snackbarText = ref('')

function notify(text: string): void {
  snackbarText.value = text
  snackbar.value = true
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [a, list] = await Promise.all([getAlbum(albumId.value), listAlbumItems(albumId.value)])
    album.value = a
    items.value = list
    selection.prune()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

// ── 絞り込み ──────────────────────────────────────
/** 絞り込みに使うタグ（tagKey の形。表記ゆれを同じものとみなす） */
const tagFilter = ref<string[]>([])
// このアルバムの画像に付いているタグを、多い順に並べる
const tagItems = computed(() => {
  const counts = new Map<string, { tag: string, count: number }>()
  for (const item of items.value) {
    for (const tag of item.image.tags) {
      const entry = counts.get(tagKey(tag)) ?? { tag, count: 0 }
      entry.count += 1
      counts.set(tagKey(tag), entry)
    }
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag, 'ja')).map((e) => e.tag)
})
const isTagFilterActive = (tag: string) => tagFilter.value.includes(tagKey(tag))

function toggleTagFilter(tag: string): void {
  const key = tagKey(tag)
  tagFilter.value = isTagFilterActive(tag) ? tagFilter.value.filter((v) => v !== key) : [...tagFilter.value, key]
}

const visible = computed<GridItem[]>(() => items.value
  .filter((item) => tagFilter.value.length === 0 || item.image.tags.some((tag) => tagFilter.value.includes(tagKey(tag))))
  .map((item) => ({ id: item.image.id, image: item.image })))

const selection = useSelection(() => visible.value)
watch(tagFilter, () => selection.clear())

// 絞り込んでいたタグが、タグ付けで無くなったら外す
watch(tagItems, (tags) => {
  const keys = new Set(tags.map(tagKey))
  if (tagFilter.value.some((key) => !keys.has(key))) tagFilter.value = tagFilter.value.filter((key) => keys.has(key))
})

// ── 詳細 ──────────────────────────────────────────
const detailOpen = ref(false)
const detailIndex = ref(0)
function openDetail(index: number): void {
  detailIndex.value = index
  detailOpen.value = true
}

// ── 一括操作 ──────────────────────────────────────
const selectedIds = computed(() => [...selection.selected.value])

async function run(action: () => Promise<string>): Promise<void> {
  busy.value = true
  error.value = null
  try {
    notify(await action())
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

// ── タグ付け ──────────────────────────────────────
const tagOpen = ref(false)
const tagSuggestions = ref<string[]>([])
watch(tagOpen, (open) => {
  if (open) fetchTags().then((list) => { tagSuggestions.value = list.map((t) => t.tag) }).catch(() => {})
})
const selectedTags = computed(() =>
  uniqueTags(items.value.filter((i) => selection.selected.value.has(i.image.id)).flatMap((i) => i.image.tags)),
)

async function applyTags(tags: string[], mode: TagMode): Promise<void> {
  const res = await batchTags(selectedIds.value, tags, mode)
  notify(`${res.updated} 枚のタグを更新しました`)
  await load()
}

const removeOpen = ref(false)
async function removeSelected(): Promise<void> {
  await run(async () => {
    const res = await removeAlbumItems(albumId.value, selectedIds.value)
    selection.clear()
    return `${res.removed} 枚をアルバムから外しました`
  })
  removeOpen.value = false
}

const editOpen = ref(false)
const editName = ref('')
const editDescription = ref('')
const editError = ref<string | null>(null)
watch(editOpen, (open) => {
  if (!open) return
  editName.value = album.value?.name ?? ''
  editDescription.value = album.value?.description ?? ''
  editError.value = null
})

async function saveEdit(): Promise<void> {
  busy.value = true
  editError.value = null
  try {
    album.value = await updateAlbum(albumId.value, { name: editName.value.trim(), description: editDescription.value })
    editOpen.value = false
  } catch (e) {
    editError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

const deleteOpen = ref(false)
async function removeAlbum(): Promise<void> {
  busy.value = true
  try {
    await deleteAlbum(albumId.value)
    await router.push('/albums')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

watch(albumId, load)
onMounted(load)
</script>

<style scoped>
.album {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  height: calc(100dvh - var(--app-top));
}
.pane { display: flex; flex-direction: column; min-height: 0; }
.pane--center { gap: var(--sp-2); padding: var(--sp-3) var(--sp-3) 0; }
.head { display: flex; align-items: center; gap: var(--sp-2); padding: 0 var(--sp-1); }
.head__title { min-width: 0; }
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
.filter-bar__total { padding: 0 var(--sp-1); color: var(--ink-2); font-size: var(--fs-sm); }
.filter-bar__count { padding: 0 var(--sp-1); color: var(--text-brand); font-size: var(--fs-sm); }
.filter-bar__hint { color: var(--ink-4); font-size: var(--fs-xs); white-space: nowrap; }
.filter-bar__label { margin-left: var(--sp-2); color: var(--ink-3); font-size: var(--fs-sm); }
.grid-area { flex: 1; min-height: 0; }
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
</style>
