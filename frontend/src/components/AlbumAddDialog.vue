<template>
  <v-dialog v-model="dialog" max-width="480" scrollable>
    <v-card>
      <v-card-title class="dialog-title">アルバムに追加</v-card-title>
      <v-card-text class="form">
        <!-- 取り違えを防ぐため、対象の枚数をそのまま出す -->
        <div>{{ count }} 枚の画像を追加します。</div>
        <v-alert v-if="error" type="error" closable @click:close="error = null">{{ error }}</v-alert>

        <div class="field-label">追加先のアルバム</div>
        <div class="album-list">
          <div v-if="!loading && albums.length === 0" class="meta-text">
            アルバムはまだありません。<router-link to="/albums" @click="dialog = false">アルバム</router-link>のタブで作ってください。
          </div>
          <button
            v-for="album in albums"
            :key="album.id"
            type="button"
            class="album-row"
            :class="{ 'album-row--active': album.id === targetId }"
            @click="targetId = album.id"
          >
            <v-icon :icon="album.id === targetId ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank'" size="18" class="album-row__radio" />
            <div class="album-row__cover">
              <img v-if="album.cover_image_id" :src="thumbUrl(album.cover_image_id)" alt="" loading="lazy">
              <v-icon v-else icon="mdi-image-outline" size="18" />
            </div>
            <div class="album-row__body">
              <div class="album-row__name">{{ album.name }}</div>
              <div class="meta-text">{{ album.item_count }} 枚<template v-if="groups.length > 1"> ・ {{ album.group_name }}</template></div>
            </div>
          </button>
        </div>

      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="adding" @click="dialog = false">キャンセル</v-btn>
        <v-btn color="primary" variant="flat" :disabled="!targetId || imageIds.length === 0" :loading="adding" @click="add">
          {{ targetName ? `「${targetName}」に追加` : '追加' }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
/** 選んだ画像をアルバムに追加する。どのアルバムに入れるかは、ここで選ぶ（アルバムを作るのはアルバムのタブ）。 */
import { computed, ref, watch } from 'vue'
import { addAlbumItems, useAlbums } from '@/composables/useAlbums'
import { thumbUrl } from '@/composables/imagesApi'
import { useAuth } from '@/composables/useAuth'
import { useStoredRef } from '@/composables/useStoredRef'

const props = defineProps<{
  modelValue: boolean
  imageIds:   string[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 追加できた。親は結果を知らせる */
  added: [message: string]
}>()

const dialog = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
const count = computed(() => props.imageIds.length)

const { albums, loading, error, fetchAlbums } = useAlbums()
const { groups } = useAuth()
// 続けて同じアルバムに足していく使い方が多いので、最後に選んだものを覚えておく
const targetId = useStoredRef<string | null>('kazayomi.albumTarget', null)
const targetName = computed(() => albums.value.find((a) => a.id === targetId.value)?.name ?? '')

const adding = ref(false)

watch(dialog, async (open) => {
  if (!open) return
  error.value = null
  await fetchAlbums()
  if (targetId.value && !albums.value.some((a) => a.id === targetId.value)) targetId.value = null
})

async function add(): Promise<void> {
  if (!targetId.value) return
  adding.value = true
  error.value = null
  try {
    const result = await addAlbumItems(targetId.value, props.imageIds)
    const skipped = result.skipped ? `（${result.skipped} 枚は追加済み）` : ''
    emit('added', `「${targetName.value}」に ${result.added} 枚を追加しました${skipped}`)
    dialog.value = false
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    adding.value = false
  }
}
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
.album-list { display: flex; flex-direction: column; gap: var(--sp-1); max-height: 280px; overflow-y: auto; }
.album-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-1) var(--sp-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.album-row:hover { background: var(--surface-subtle); }
.album-row--active { border-color: var(--border-brand); background: var(--surface-accent); }
.album-row__radio { flex: none; color: var(--text-brand); }
.album-row__cover {
  display: grid;
  place-items: center;
  flex: none;
  width: 36px;
  height: 36px;
  overflow: hidden;
  border-radius: var(--radius-sm);
  color: var(--ink-4);
  background: var(--surface-muted);
}
.album-row__cover img { width: 100%; height: 100%; object-fit: cover; }
.album-row__body { flex: 1; min-width: 0; }
.album-row__name { overflow: hidden; color: var(--ink-1); font-size: var(--fs-sm); font-weight: var(--fw-medium); text-overflow: ellipsis; white-space: nowrap; }
</style>
