<template>
  <v-dialog v-model="dialog" fullscreen transition="fade-transition">
    <div v-if="current" class="detail" tabindex="0" @keydown="onKey">
      <div class="detail__viewer">
        <div class="detail__stage">
          <img
            :key="current.id"
            ref="imgEl"
            :src="fileUrl(current.id)"
            :alt="current.source_name || current.captured_at"
            class="detail__img"
            draggable="false"
          >
          <MarkerOverlay
            ref="overlay"
            :image="imgEl"
            :markers="current.markers ?? []"
            :editing="editingMarkers"
            :visible="showMarkers || editingMarkers"
            @selection="(state) => markerState = state"
          />
        </div>
        <v-btn
          class="detail__nav detail__nav--prev"
          icon="mdi-chevron-left"
          variant="tonal"
          :disabled="index <= 0 || editingMarkers"
          aria-label="前の画像"
          @click="move(-1)"
        />
        <v-btn
          class="detail__nav detail__nav--next"
          icon="mdi-chevron-right"
          variant="tonal"
          :disabled="index >= images.length - 1 || editingMarkers"
          aria-label="次の画像"
          @click="move(1)"
        />
        <div class="detail__counter">{{ index + 1 }} / {{ images.length }}</div>
      </div>

      <aside class="detail__side">
        <div class="detail__head">
          <div class="section-title">画像の詳細</div>
          <v-spacer />
          <v-btn icon="mdi-close" variant="text" aria-label="閉じる" @click="dialog = false" />
        </div>

        <v-alert v-if="error" type="error" closable @click:close="error = null">{{ error }}</v-alert>

        <dl class="meta">
          <dt>撮像日時</dt><dd>{{ formatDateTime(current.captured_at) }}</dd>
          <dt>ルーム</dt><dd>{{ current.room_name || (current.source === 'upload' ? '手動で取り込み' : '—') }}</dd>
          <template v-if="current.captured_by"><dt>{{ current.source === 'upload' ? '取り込んだ人' : '撮像した人' }}</dt><dd>{{ capturedByLabel(current.captured_by) }}</dd></template>
          <dt>大きさ</dt><dd>{{ current.width }}×{{ current.height }}（{{ formatBytes(current.size_bytes) }}）</dd>
          <template v-if="current.source_name"><dt>元のファイル名</dt><dd>{{ current.source_name }}</dd></template>
        </dl>

        <div class="row">
          <v-btn
            :prepend-icon="current.favorite ? 'mdi-star' : 'mdi-star-outline'"
            :color="current.favorite ? 'warning' : undefined"
            :variant="current.favorite ? 'flat' : 'outlined'"
            @click="toggleFavorite"
          >お気に入り</v-btn>
          <v-btn
            :prepend-icon="playing ? 'mdi-pause' : 'mdi-play'"
            variant="outlined"
            :disabled="images.length < 2"
            @click="playing = !playing"
          >スライドショー</v-btn>
        </div>

        <!-- 図形（楕円・多角形・吹き出し） -->
        <div class="markers">
          <div class="markers__head">
            <span class="field-label">図形</span>
            <span class="meta-text">{{ markerCountText }}</span>
            <v-spacer />
            <v-switch
              v-if="!editingMarkers && (current.markers?.length ?? 0) > 0"
              v-model="showMarkers"
              label="表示"
              density="compact"
              hide-details
              color="primary"
            />
            <v-btn
              v-if="canEdit && !editingMarkers"
              size="small"
              variant="outlined"
              prepend-icon="mdi-pencil-outline"
              @click="startEditingMarkers"
            >図形を描く</v-btn>
          </div>
          <template v-if="editingMarkers">
            <div class="markers__tools">
              <v-btn icon="mdi-ellipse-outline" size="small" variant="tonal" title="楕円を追加" aria-label="楕円を追加" @click="overlay?.addEllipse()" />
              <v-btn icon="mdi-comment-text-outline" size="small" variant="tonal" title="吹き出しを追加" aria-label="吹き出しを追加" @click="addCallout" />
              <v-btn
                icon="mdi-vector-polygon"
                size="small"
                :variant="markerState.drawing ? 'flat' : 'tonal'"
                :color="markerState.drawing ? 'primary' : undefined"
                title="多角形を描く"
                aria-label="多角形を描く"
                @click="markerState.drawing ? overlay?.finishPolygon() : overlay?.startPolygon()"
              />
              <v-btn icon="mdi-plus-circle-outline" size="small" variant="tonal" :disabled="!markerState.vertex" title="頂点を追加" aria-label="頂点を追加" @click="overlay?.addVertex()" />
              <v-btn icon="mdi-minus-circle-outline" size="small" variant="tonal" :disabled="!markerState.vertex" title="頂点を削除" aria-label="頂点を削除" @click="overlay?.removeVertex()" />
              <v-btn icon="mdi-delete-outline" size="small" variant="tonal" color="error" :disabled="!markerState.item" title="選んだ図形を削除" aria-label="選んだ図形を削除" @click="overlay?.deleteSelected()" />
            </div>
            <!-- 吹き出しを選んでいるときだけ、その文字を書き換えられる -->
            <v-textarea
              v-if="markerState.calloutText !== null"
              ref="calloutField"
              :model-value="markerState.calloutText"
              label="吹き出しの文字"
              rows="2"
              auto-grow
              counter="200"
              maxlength="200"
              hide-details="auto"
              @update:model-value="(text: string) => { markerState.calloutText = text; overlay?.setCalloutText(text) }"
            />
            <p class="meta-text">{{ markerHint }}</p>
            <div class="row">
              <v-btn variant="text" :disabled="savingMarkers" @click="cancelEditingMarkers">キャンセル</v-btn>
              <v-btn color="primary" :loading="savingMarkers" @click="saveMarkers">図形を保存</v-btn>
            </div>
          </template>
        </div>

        <!-- タグは表示だけ。付け外しはライブラリ・アルバムの「タグ付け」で行う -->
        <div class="tags">
          <span class="field-label">タグ</span>
          <div class="tags__chips">
            <v-chip v-for="tag in current.tags" :key="tag" size="small" color="secondary" variant="tonal">#{{ tag }}</v-chip>
            <span v-if="current.tags.length === 0" class="meta-text">なし</span>
          </div>
        </div>
        <v-textarea v-model="note" label="メモ" rows="3" auto-grow :readonly="!canEdit" @update:model-value="dirty = true" />
        <div v-if="canEdit" class="row">
          <v-btn color="primary" :disabled="!dirty" :loading="saving" @click="save">メモを保存</v-btn>
        </div>

        <v-spacer />

        <div class="row">
          <v-btn prepend-icon="mdi-download-outline" variant="outlined" :href="downloadUrl(current.id)">ダウンロード</v-btn>
          <v-spacer />
          <v-btn v-if="canEdit" prepend-icon="mdi-delete-outline" color="error" variant="outlined" @click="askDelete">削除</v-btn>
        </div>
        <p class="meta-text">{{ editingMarkers ? '図形を描いている間は、前後の画像に移れません' : '← → で前後の画像、Esc で閉じます' }}</p>
      </aside>
    </div>

    <ConfirmDialog
      v-model="deleteOpen"
      title="画像を削除"
      confirm-text="削除"
      danger
      :busy="deleting"
      @confirm="confirmDelete"
    >
      この画像を削除します。元に戻せません。
      <template v-if="albumUsage > 0">この画像はアルバムにも入っています。アルバムからも外れます。</template>
    </ConfirmDialog>
  </v-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MarkerOverlay, { type MarkerSelection } from '@/components/MarkerOverlay.vue'
import {
  countAlbumUsage,
  deleteImages,
  downloadUrl,
  fileUrl,
  updateImage,
} from '@/composables/imagesApi'
import { formatBytes, formatDateTime } from '@/composables/format'
import { useAuth } from '@/composables/useAuth'
import type { ImageRecord } from '@/types'

const props = defineProps<{
  modelValue: boolean
  index:      number
  images:     ImageRecord[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:index':      [value: number]
  /** 画像を更新・削除した。親は一覧を取り直す。 */
  changed:             [kind: 'updated' | 'deleted', image: ImageRecord]
}>()

const { canIn } = useAuth()

/** Kazami の撮像ボタンで撮った画像は `device:<デバイス名>` で記録している */
function capturedByLabel(value: string): string {
  return value.startsWith('device:') ? `端末「${value.slice('device:'.length)}」` : value
}

const dialog = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
const current = computed(() => props.images[props.index] ?? null)
// 編集できるのは、画像のグループで編集の権限を持っているときだけ
const canEdit = computed(() => canIn(current.value?.group_id, 'can_edit'))

const note = ref('')
const dirty = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

watch(current, (image, previous) => {
  note.value = image?.note ?? ''
  dirty.value = false
  // 別の画像に移ったら、描きかけの図形は捨てる（同じ画像の更新では続ける）
  if (image?.id !== previous?.id) editingMarkers.value = false
}, { immediate: true })

watch(dialog, (open) => {
  if (!open) {
    playing.value = false
    editingMarkers.value = false
  }
})

function move(delta: number): void {
  const next = props.index + delta
  if (next >= 0 && next < props.images.length) emit('update:index', next)
}

function onKey(event: KeyboardEvent): void {
  // 入力欄で ← → を押したときは、カーソル移動を優先する
  const target = event.target as HTMLElement
  if (target.closest('input, textarea')) return
  if (editingMarkers.value) {
    if (event.key === 'Delete' || event.key === 'Backspace') overlay.value?.deleteSelected()
    else if (event.key === 'Enter' && markerState.value.drawing) overlay.value?.finishPolygon()
    return
  }
  if (event.key === 'ArrowLeft') move(-1)
  else if (event.key === 'ArrowRight') move(1)
}

// ── スライドショー ────────────────────────────────
const playing = ref(false)
let slideTimer: number | undefined
watch(playing, (on) => {
  window.clearInterval(slideTimer)
  if (!on) return
  slideTimer = window.setInterval(() => {
    emit('update:index', props.index >= props.images.length - 1 ? 0 : props.index + 1)
  }, 3000)
})
onBeforeUnmount(() => window.clearInterval(slideTimer))

// ── 図形 ──────────────────────────────────────────
const imgEl = ref<HTMLImageElement | null>(null)
const overlay = ref<InstanceType<typeof MarkerOverlay> | null>(null)
const showMarkers = ref(true)
const editingMarkers = ref(false)
const savingMarkers = ref(false)
const markerState = ref<MarkerSelection>({ item: false, vertex: false, drawing: false, calloutText: null })
const calloutField = ref<{ $el: HTMLElement } | null>(null)

/** 吹き出しを足したら、すぐ文字を打てるよう入力欄に移り、仮の文字を選んでおく（打てば置き換わる） */
async function addCallout(): Promise<void> {
  overlay.value?.addCallout()
  await nextTick()
  const textarea = calloutField.value?.$el.querySelector('textarea')
  textarea?.focus()
  textarea?.select()
}

const markerCountText = computed(() => {
  const count = current.value?.markers?.length ?? 0
  return count > 0 ? `${count} 個` : 'なし'
})
const markerHint = computed(() => markerState.value.drawing
  ? 'クリックで頂点を足し、最初の頂点の近くをクリック（または Enter）で閉じます。'
  : markerState.value.calloutText !== null
    ? '吹き出しはドラッグで移動、青い丸をドラッグで指す先を変えます。文字は上の欄で書き換えます（改行もできます）。'
    : '図形をドラッグで移動、Shift を押しながらドラッグで回転。楕円は右下の丸で大きさ、多角形は頂点をドラッグで形を変えます。')

function startEditingMarkers(): void {
  showMarkers.value = true
  editingMarkers.value = true
}

function cancelEditingMarkers(): void {
  editingMarkers.value = false
  overlay.value?.reset()
}

async function saveMarkers(): Promise<void> {
  if (!current.value || !overlay.value) return
  overlay.value.finishPolygon()
  savingMarkers.value = true
  error.value = null
  try {
    const updated = await updateImage(current.value.id, { markers: overlay.value.collect() })
    editingMarkers.value = false
    emit('changed', 'updated', updated)
  } catch (e) {
    // 保存できなかったときは、描いた図形を残したまま編集を続ける
    error.value = (e as Error).message
  } finally {
    savingMarkers.value = false
  }
}

// ── 更新 ──────────────────────────────────────────
async function toggleFavorite(): Promise<void> {
  if (!current.value) return
  try {
    const updated = await updateImage(current.value.id, { favorite: !current.value.favorite })
    emit('changed', 'updated', updated)
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function save(): Promise<void> {
  if (!current.value) return
  saving.value = true
  error.value = null
  try {
    const updated = await updateImage(current.value.id, { note: note.value })
    dirty.value = false
    emit('changed', 'updated', updated)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

// ── 削除 ──────────────────────────────────────────
const deleteOpen = ref(false)
const deleting = ref(false)
const albumUsage = ref(0)

async function askDelete(): Promise<void> {
  if (!current.value) return
  albumUsage.value = 0
  deleteOpen.value = true
  try {
    albumUsage.value = (await countAlbumUsage([current.value.id])).count
  } catch {
    // 件数が出なくても削除はできる
  }
}

async function confirmDelete(): Promise<void> {
  const image = current.value
  if (!image) return
  deleting.value = true
  try {
    await deleteImages([image.id])
    deleteOpen.value = false
    // 最後の 1 枚を消したら閉じる。それ以外は同じ位置（次の画像）を出す
    if (props.images.length <= 1) dialog.value = false
    else if (props.index >= props.images.length - 1) emit('update:index', props.index - 1)
    emit('changed', 'deleted', image)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  height: 100vh;
  background: var(--surface-page);
  outline: none;
}
.detail__viewer {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 0;
  background: var(--surface-inverse-deep);
}
.detail__stage {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.detail__img { max-width: 100%; max-height: 100vh; object-fit: contain; user-select: none; }
.tags { display: flex; flex-direction: column; gap: var(--sp-1); }
.tags__chips { display: flex; flex-wrap: wrap; gap: var(--sp-1); }
.markers {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}
.markers__head { display: flex; align-items: center; gap: var(--sp-2); min-height: 32px; }
.markers__head :deep(.v-switch) { flex: none; }
.markers__tools { display: flex; gap: var(--sp-1); flex-wrap: wrap; }
.detail__nav { position: absolute; z-index: 2; top: 50%; transform: translateY(-50%); }
.detail__nav--prev { left: var(--sp-4); }
.detail__nav--next { right: var(--sp-4); }
.detail__counter {
  position: absolute;
  bottom: var(--sp-3);
  left: 50%;
  transform: translateX(-50%);
  padding: 2px var(--sp-3);
  border-radius: var(--radius-pill);
  color: var(--text-on-inverse);
  background: color-mix(in srgb, var(--surface-inverse-deep) 70%, transparent);
  font-size: var(--fs-sm);
}
.detail__side {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  overflow-y: auto;
  border-left: 1px solid var(--border-default);
  background: var(--surface-card);
}
.detail__head { display: flex; align-items: center; }
.meta {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--sp-1) var(--sp-3);
  margin: 0;
  font-size: var(--fs-sm);
}
.meta dt { color: var(--ink-4); }
.meta dd { margin: 0; color: var(--ink-1); word-break: break-all; }
.row { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
</style>
