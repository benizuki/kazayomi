<template>
  <div>
    <MasterToolbar v-model="search" add-label="ユーザーを追加" placeholder="メール・名前で絞り込み" @add="openEdit(null)" />
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>

    <v-data-table
      :headers="headers"
      :items="users.items.value"
      :loading="users.loading.value"
      :search="search"
      no-data-text="ユーザーがいません"
      loading-text="読み込み中…"
      items-per-page-text="表示件数"
    >
      <template #item.name="{ item }">
        <div class="cell-main">{{ item.name }}</div>
        <div class="meta-text">{{ item.email }}</div>
      </template>
      <template #item.role="{ item }">
        <span class="chip chip--sm" :class="item.role === 'admin' ? 'chip--brand' : ''">{{ ROLE_LABELS[item.role] }}</span>
      </template>
      <template #item.group_ids="{ item }">
        <span v-if="item.role === 'admin'" class="meta-text">全グループ</span>
        <span
          v-for="g in item.group_ids"
          v-else
          :key="g"
          class="chip chip--sm group-chip"
          :class="item.group_roles[g] === 'owner' ? 'chip--info' : ''"
          :title="item.group_roles[g] === 'owner' ? 'グループ管理者' : undefined"
        >{{ groupName(g) }}<template v-if="item.group_roles[g] === 'owner'">（管理）</template></span>
        <span v-if="item.role !== 'admin' && item.group_ids.length === 0" class="chip chip--sm chip--warn">所属なし</span>
      </template>
      <template #item.enabled="{ item }">
        <span class="chip chip--sm chip--pill" :class="item.enabled ? 'chip--brand' : 'chip--danger'">{{ item.enabled ? '有効' : '無効' }}</span>
      </template>
      <template #item.last_login_at="{ item }">
        <span class="meta-text">{{ item.last_login_at ? formatDateTime(item.last_login_at) : '—' }}</span>
      </template>
      <template #item.actions="{ item }">
        <v-btn icon="mdi-pencil-outline" variant="text" size="small" aria-label="編集" @click="openEdit(item)" />
        <v-btn icon="mdi-delete-outline" variant="text" size="small" aria-label="削除" :disabled="item.email === me?.user.email" @click="askDelete(item)" />
      </template>
    </v-data-table>

    <v-dialog v-model="editOpen" max-width="520">
      <v-card>
        <v-card-title class="dialog-title">{{ editing ? 'ユーザーを編集' : 'ユーザーを追加' }}</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <v-text-field v-model="form.email" label="メールアドレス（Google のログインID）" autofocus />
          <v-text-field v-model="form.name" label="表示名（空欄なら最初のログインで Google の名前を使います）" />
          <v-select v-model="form.role" :items="roleItems" label="ロール" />
          <p class="meta-text">{{ ROLE_HINTS[form.role] }}</p>
          <v-select
            v-model="form.group_ids"
            :items="groups.items.value"
            item-title="name"
            item-value="id"
            label="所属グループ"
            multiple
            chips
            closable-chips
            :disabled="form.role === 'admin'"
            :hint="form.role === 'admin' ? '管理者は全グループを見られます' : 'このグループのルーム・画像・アルバムだけを見られます。グループでの役割はマスター › メンバーで変えます'"
            persistent-hint
          />
          <v-checkbox v-model="form.enabled" label="有効（外すとログインできなくなります）" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!form.email" @click="save">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="deleteOpen" title="ユーザーを削除" confirm-text="削除" danger :busy="saving" @confirm="confirmDelete">
      {{ deleteTarget?.email }} を削除します。この人はログインできなくなります（一時的に止めるだけなら「有効」を外してください）。
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MasterToolbar from '@/components/masters/MasterToolbar.vue'
import { formatDateTime } from '@/composables/format'
import { useAuth } from '@/composables/useAuth'
import { useGroupsMaster, useUsersMaster } from '@/composables/useMasters'
import type { Role, UserInput, UserRecord } from '@/types'

const ROLE_LABELS: Record<Role, string> = { admin: '管理者', device_admin: 'デバイス管理者', power: '編集者', user: '閲覧者' }
const ROLE_HINTS: Record<Role, string> = {
  admin:        'すべての操作と、ユーザー・グループの管理ができます。',
  device_admin: '画像・アルバムの編集に加えて、サーバ・ルーム・デバイスを管理できます。',
  power:        '映像を見て撮像し、タグ・アルバムの編集や画像の削除・取り込みができます。',
  user:         '映像を見て撮像し、画像とアルバムを見られます（編集はできません）。',
}
const roleItems = (Object.keys(ROLE_LABELS) as Role[]).map((value) => ({ title: ROLE_LABELS[value], value }))

const headers = [
  { title: 'ユーザー', key: 'name' },
  { title: 'ロール', key: 'role' },
  { title: '所属グループ', key: 'group_ids', sortable: false },
  { title: '状態', key: 'enabled' },
  { title: '最終ログイン', key: 'last_login_at' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const { me } = useAuth()
const users = useUsersMaster()
const groups = useGroupsMaster()
const search = ref('')
const error = ref<string | null>(null)

function groupName(id: string): string {
  return groups.items.value.find((g) => g.id === id)?.name ?? id
}

const editOpen = ref(false)
const editing = ref<UserRecord | null>(null)
const form = reactive<UserInput>({ email: '', name: '', role: 'user', enabled: true, group_ids: [] })
const formError = ref<string | null>(null)
const saving = ref(false)

function openEdit(user: UserRecord | null): void {
  editing.value = user
  formError.value = null
  Object.assign(form, user
    ? { email: user.email, name: user.name, role: user.role, enabled: user.enabled, group_ids: [...user.group_ids] }
    : { email: '', name: '', role: 'user', enabled: true, group_ids: groups.items.value.length === 1 ? [groups.items.value[0].id] : [] })
  editOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    await users.save({ ...form }, editing.value?.id)
    editOpen.value = false
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

const deleteOpen = ref(false)
const deleteTarget = ref<UserRecord | null>(null)

function askDelete(user: UserRecord): void {
  deleteTarget.value = user
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await users.remove(deleteTarget.value.id)
    deleteOpen.value = false
  } catch (e) {
    error.value = (e as Error).message
    deleteOpen.value = false
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([users.fetchAll(), groups.fetchAll()])
  error.value = users.error.value ?? groups.error.value
})
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
.cell-main { color: var(--ink-1); font-weight: var(--fw-medium); }
.group-chip { margin: 1px 2px 1px 0; }
</style>
