<template>
  <div>
    <MasterToolbar v-model="search" add-label="グループを追加" @add="openEdit(null)" />
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>

    <v-data-table
      :headers="headers"
      :items="groups.items.value"
      :loading="groups.loading.value"
      :search="search"
      no-data-text="グループがありません"
      loading-text="読み込み中…"
      items-per-page-text="表示件数"
    >
      <template #item.id="{ item }"><code>{{ item.id }}</code></template>
      <template #item.room_count="{ item }"><span class="numeric">{{ item.room_count }}</span></template>
      <template #item.user_count="{ item }"><span class="numeric">{{ item.user_count }}</span></template>
      <template #item.usage_bytes="{ item }">
        <UsageMeter :usage="item.usage_bytes" :quota="item.quota_bytes" />
        <div class="meta-text">画像 {{ item.image_count }} 枚</div>
      </template>
      <template #item.actions="{ item }">
        <v-btn icon="mdi-pencil-outline" variant="text" size="small" aria-label="編集" @click="openEdit(item)" />
        <v-btn icon="mdi-delete-outline" variant="text" size="small" aria-label="削除" @click="askDelete(item)" />
      </template>
    </v-data-table>

    <v-dialog v-model="editOpen" max-width="480">
      <v-card>
        <v-card-title class="dialog-title">{{ editing ? 'グループを編集' : 'グループを追加' }}</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <v-text-field
            v-model="form.id"
            label="グループID（半角英数字と _ -）"
            :disabled="!!editing"
            :hint="editing ? '画像やアルバムが参照しているため変えられません' : 'あとから変えられません'"
            persistent-hint
            autofocus
          />
          <v-text-field v-model="form.name" label="グループ名" />
          <v-text-field
            v-model="form.quotaMb"
            label="容量の上限（MB）"
            type="number"
            min="0"
            step="10"
            placeholder="空なら無制限"
            hint="画像とサムネイルの合計。超えると、このグループには画像を保存できなくなります（Kazami にも理由を返します）"
            persistent-hint
          />
          <p v-if="editing" class="meta-text">いまの使用量: {{ formatBytes(editing.usage_bytes) }}（画像 {{ editing.image_count }} 枚）</p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!form.id || !form.name" @click="save">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="deleteOpen" title="グループを削除" confirm-text="削除" danger :busy="saving" @confirm="confirmDelete">
      「{{ deleteTarget?.name }}」を削除します。ルーム・画像・アルバムが残っているグループは削除できません。
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MasterToolbar from '@/components/masters/MasterToolbar.vue'
import UsageMeter from '@/components/masters/UsageMeter.vue'
import { formatBytes } from '@/composables/format'
import { fetchAppSettings, useGroupsMaster } from '@/composables/useMasters'
import { toBytes, toMb } from '@/composables/quota'
import type { AppSettings, Group } from '@/types'

const headers = [
  { title: 'グループID', key: 'id' },
  { title: 'グループ名', key: 'name' },
  { title: 'ルーム', key: 'room_count', align: 'end' as const },
  { title: 'ユーザー', key: 'user_count', align: 'end' as const },
  { title: '容量', key: 'usage_bytes' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const groups = useGroupsMaster()
const search = ref('')
const error = ref<string | null>(null)

const editOpen = ref(false)
const editing = ref<Group | null>(null)
const form = reactive<{ id: string; name: string; quotaMb: string }>({ id: '', name: '', quotaMb: '' })
const formError = ref<string | null>(null)
const saving = ref(false)

function openEdit(group: Group | null): void {
  editing.value = group
  formError.value = null
  // 新しいグループは「新しいグループの容量」で始める
  const quota = group ? group.quota_bytes : settings.value?.default_group_quota_bytes ?? null
  Object.assign(form, { id: group?.id ?? '', name: group?.name ?? '', quotaMb: toMb(quota) })
  editOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    await groups.save({ id: form.id, name: form.name, quota_bytes: toBytes(form.quotaMb) }, editing.value?.id)
    editOpen.value = false
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

const deleteOpen = ref(false)
const deleteTarget = ref<Group | null>(null)

function askDelete(group: Group): void {
  deleteTarget.value = group
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await groups.remove(deleteTarget.value.id)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
    deleteOpen.value = false
  }
}

// 新しいグループは「新しいグループの容量」（マスター › 設定）で始める
const settings = ref<AppSettings | null>(null)

onMounted(async () => {
  const [, loaded] = await Promise.all([groups.fetchAll(), fetchAppSettings().catch((e: Error) => { error.value = e.message; return null })])
  settings.value = loaded
  error.value = error.value ?? groups.error.value
})
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
code { font-family: var(--font-mono); font-size: var(--fs-xs); }

</style>
