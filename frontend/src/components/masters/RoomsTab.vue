<template>
  <div>
    <MasterToolbar v-model="search" add-label="ルームを追加" placeholder="名前・ルームIDで絞り込み" @add="openEdit(null)">
      <v-select
        v-model="groupFilter"
        :items="groups.items.value"
        item-title="name"
        item-value="id"
        label="グループ"
        density="compact"
        clearable
        class="filter"
      />
    </MasterToolbar>
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>

    <v-data-table
      :headers="headers"
      :items="filtered"
      :loading="rooms.loading.value"
      :search="search"
      no-data-text="ルームがありません"
      loading-text="読み込み中…"
      items-per-page-text="表示件数"
    >
      <template #item.ayame_room_id="{ item }"><code>{{ item.ayame_room_id }}</code></template>
      <template #item.group_name="{ item }"><span class="chip chip--sm">{{ item.group_name }}</span></template>
      <template #item.server_name="{ item }">
        <span v-if="item.server_id">{{ item.server_name }}</span>
        <span v-else-if="item.server_name" class="meta-text">既定（{{ item.server_name }}）</span>
        <span v-else class="chip chip--sm chip--warn">サーバ未設定</span>
      </template>
      <template #item.actions="{ item }">
        <v-btn icon="mdi-open-in-new" variant="text" size="small" aria-label="映像を開く" :to="`/view/${item.id}`" />
        <v-btn icon="mdi-pencil-outline" variant="text" size="small" aria-label="編集" @click="openEdit(item)" />
        <v-btn icon="mdi-delete-outline" variant="text" size="small" aria-label="削除" @click="askDelete(item)" />
      </template>
    </v-data-table>

    <v-dialog v-model="editOpen" max-width="520">
      <v-card>
        <v-card-title class="dialog-title">{{ editing ? 'ルームを編集' : 'ルームを追加' }}</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <v-text-field v-model="form.name" label="ルーム名" autofocus />
          <v-text-field v-model="form.ayame_room_id" label="ルームID" hint="Kazami の設定の「Room ID」と同じ値" persistent-hint />
          <v-select
            v-model="form.group_id"
            :items="groups.items.value"
            item-title="name"
            item-value="id"
            label="グループ"
            :hint="editing ? 'グループを変えても、撮像済みの画像は撮った時点のグループのままです' : 'このグループのユーザーだけが見られます'"
            persistent-hint
          />
          <v-select
            v-model="form.server_id"
            :items="serverItems"
            label="サーバ"
            hint="Ayame のシグナリングサーバ。「既定のサーバ」にしておくと、マスター › サーバで既定を変えたときに一緒に変わります"
            persistent-hint
          />
          <v-textarea v-model="form.note" label="メモ（任意）" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!form.name || !form.ayame_room_id || !form.group_id" @click="save">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="deleteOpen" title="ルームを削除" confirm-text="削除" danger :busy="saving" @confirm="confirmDelete">
      「{{ deleteTarget?.name }}」を削除します。撮像した画像はライブラリに残ります。
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MasterToolbar from '@/components/masters/MasterToolbar.vue'
import { useRoomsMaster, useGroupsMaster, useServersMaster } from '@/composables/useMasters'
import type { Room, RoomInput } from '@/types'

const headers = [
  { title: 'ルーム名', key: 'name' },
  { title: 'ルームID', key: 'ayame_room_id' },
  { title: 'グループ', key: 'group_name' },
  { title: 'サーバ', key: 'server_name' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const rooms = useRoomsMaster()
const groups = useGroupsMaster()
const servers = useServersMaster()
const search = ref('')
const groupFilter = ref<string | null>(null)
const error = ref<string | null>(null)

const filtered = computed(() => rooms.items.value.filter((c) => !groupFilter.value || c.group_id === groupFilter.value))
const serverItems = computed(() => {
  const fallback = servers.items.value.find((s) => s.is_default)
  return [
    { title: fallback ? `既定のサーバ（いまは ${fallback.name}）` : '既定のサーバ（未設定。マスター › サーバで決めてください）', value: null },
    ...servers.items.value.map((s) => ({ title: `${s.name}（${s.signaling_url}）`, value: s.id })),
  ]
})

const editOpen = ref(false)
const editing = ref<Room | null>(null)
const form = reactive<RoomInput>({ name: '', ayame_room_id: '', group_id: '', server_id: null, note: '' })
const formError = ref<string | null>(null)
const saving = ref(false)

function openEdit(room: Room | null): void {
  editing.value = room
  formError.value = null
  Object.assign(form, room
    ? { name: room.name, ayame_room_id: room.ayame_room_id, group_id: room.group_id, server_id: room.server_id, note: room.note }
    : { name: '', ayame_room_id: '', group_id: groupFilter.value ?? groups.items.value[0]?.id ?? '', server_id: null, note: '' })
  editOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    await rooms.save({ ...form }, editing.value?.id)
    editOpen.value = false
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

const deleteOpen = ref(false)
const deleteTarget = ref<Room | null>(null)

function askDelete(room: Room): void {
  deleteTarget.value = room
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await rooms.remove(deleteTarget.value.id)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
    deleteOpen.value = false
  }
}

onMounted(async () => {
  await Promise.all([rooms.fetchAll(), groups.fetchAll(), servers.fetchAll()])
  error.value = rooms.error.value ?? groups.error.value ?? servers.error.value
})
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
.filter { max-width: 220px; }
code { font-family: var(--font-mono); font-size: var(--fs-xs); }
</style>
