<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">アルバム</h1>
        <p class="page-lead">ライブラリから集めた画像のまとまりです。タグで絞り込み、ZIP でまとめて書き出せます。</p>
      </div>
      <v-spacer />
      <v-btn v-if="permissions.can_edit" color="primary" prepend-icon="mdi-plus" @click="createOpen = true">アルバムを作る</v-btn>
    </header>

    <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

    <div v-if="!loading && albums.length === 0" class="empty-state">
      <v-icon icon="mdi-folder-star-outline" size="40" />
      <p>アルバムはまだありません。「アルバムを作る」から作り、ライブラリで画像を選んで「アルバムに追加」で入れます。</p>
    </div>

    <div class="grid">
      <v-card v-for="album in albums" :key="album.id" :to="`/albums/${album.id}`" class="album-card">
        <div class="album-card__cover">
          <img v-if="album.cover_image_id" :src="thumbUrl(album.cover_image_id)" alt="" loading="lazy">
          <v-icon v-else icon="mdi-image-outline" size="36" />
        </div>
        <div class="album-card__body">
          <div class="album-card__name">{{ album.name }}</div>
          <div class="album-card__chips">
            <span class="chip chip--sm">{{ album.item_count }} 枚</span>
            <span v-if="groups.length > 1" class="chip chip--sm chip--info">{{ album.group_name }}</span>
          </div>
          <div class="meta-text">更新 {{ formatDateTime(album.updated_at) }}</div>
        </div>
      </v-card>
    </div>

    <v-dialog v-model="createOpen" max-width="480">
      <v-card>
        <v-card-title class="dialog-title">アルバムを作る</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="createError" type="error">{{ createError }}</v-alert>
          <v-select
            v-if="editableGroups.length > 1"
            v-model="newGroupId"
            :items="editableGroups"
            item-title="name"
            item-value="id"
            label="グループ"
            hint="このグループの画像だけを入れられます"
            persistent-hint
          />
          <v-text-field v-model="newName" label="アルバム名" autofocus />
          <v-textarea v-model="newDescription" label="説明（任意）" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="createOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :disabled="!newName.trim()" :loading="creating" @click="create">作る</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { formatDateTime } from '@/composables/format'
import { thumbUrl } from '@/composables/imagesApi'
import { useAlbums } from '@/composables/useAlbums'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const { albums, loading, error, fetchAlbums, createAlbum } = useAlbums()

const { permissions, groups, canIn } = useAuth()
// アルバムを作れるのは、編集の権限を持っているグループだけ
const editableGroups = computed(() => groups.value.filter((g) => canIn(g.id, 'can_edit')))
const createOpen = ref(false)
const newGroupId = ref(editableGroups.value[0]?.id ?? '')
const newName = ref('')
const newDescription = ref('')
const creating = ref(false)
const createError = ref<string | null>(null)

watch(createOpen, (open) => {
  if (!open) return
  if (!editableGroups.value.some((g) => g.id === newGroupId.value)) newGroupId.value = editableGroups.value[0]?.id ?? ''
  newName.value = ''
  newDescription.value = ''
  createError.value = null
})

async function create(): Promise<void> {
  creating.value = true
  createError.value = null
  try {
    const album = await createAlbum(newName.value.trim(), newDescription.value, newGroupId.value)
    createOpen.value = false
    await router.push(`/albums/${album.id}`)
  } catch (e) {
    createError.value = (e as Error).message
  } finally {
    creating.value = false
  }
}

onMounted(fetchAlbums)
</script>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--sp-4); }
.album-card { overflow: hidden; }
.album-card__cover {
  display: grid;
  place-items: center;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  color: var(--ink-4);
  background: var(--surface-muted);
}
.album-card__cover img { width: 100%; height: 100%; object-fit: cover; }
.album-card__body { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-3) var(--sp-4) var(--sp-4); }
.album-card__name { color: var(--ink-1); font-size: var(--fs-md); font-weight: var(--fw-bold); }
.album-card__chips { display: flex; flex-wrap: wrap; gap: var(--sp-1); }
.form { display: flex; flex-direction: column; gap: var(--sp-4); }
</style>
