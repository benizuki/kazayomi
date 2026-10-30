<template>
  <div>
    <MasterToolbar v-model="search" add-label="サーバを追加" @add="openEdit(null)" />
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>

    <v-data-table
      :headers="headers"
      :items="servers.items.value"
      :loading="servers.loading.value"
      :search="search"
      no-data-text="サーバがありません。サーバを登録して既定にするまで、ルームはつなげません"
      loading-text="読み込み中…"
      items-per-page-text="表示件数"
    >
      <template #item.name="{ item }">
        {{ item.name }}
        <span v-if="item.is_default" class="chip chip--sm chip--brand default-chip">既定</span>
      </template>
      <template #item.kind="{ item }">
        <span class="chip chip--sm">{{ kindLabel(item.kind) }}</span>
      </template>
      <template #item.signaling_url="{ item }"><code>{{ item.signaling_url }}</code></template>
      <template #item.room_count="{ item }"><span class="numeric">{{ item.room_count }}</span></template>
      <template #item.actions="{ item }">
        <v-btn
          v-if="!item.is_default"
          icon="mdi-star-outline"
          variant="text"
          size="small"
          :aria-label="`${item.name} を既定のサーバにする`"
          title="既定のサーバにする"
          @click="makeDefault(item)"
        />
        <v-btn icon="mdi-pencil-outline" variant="text" size="small" aria-label="編集" @click="openEdit(item)" />
        <v-btn icon="mdi-delete-outline" variant="text" size="small" aria-label="削除" @click="askDelete(item)" />
      </template>
    </v-data-table>

    <v-dialog v-model="editOpen" max-width="520">
      <v-card>
        <v-card-title class="dialog-title">{{ editing ? 'サーバを編集' : 'サーバを追加' }}</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <v-text-field v-model="form.name" label="サーバ名" autofocus />
          <v-select
            v-model="form.kind"
            :items="kindItems"
            label="種類"
            hint="Cloudflare TURN にすると、入室のたびに TURN の認証情報を発行して、ブラウザと Kazami に渡します"
            persistent-hint
          />
          <v-text-field
            v-model="form.signaling_url"
            label="シグナリングURL"
            placeholder="wss://ayame.example.com/signaling"
            hint="kazayomi と Kazami の両方から届く URL にします（ブラウザは kazayomi を経由します）。localhost は不可"
            persistent-hint
          />
          <template v-if="form.kind === 'cloudflare'">
            <v-text-field v-model="form.turn_key_id" label="TURN キー ID" hint="Cloudflare ダッシュボードの Realtime → TURN で作ったキー" persistent-hint />
            <v-text-field
              v-model="form.turn_api_token"
              label="API トークン"
              type="password"
              autocomplete="new-password"
              :placeholder="editing?.turn_api_token_set ? '設定済み（変えるときだけ入力）' : ''"
              persistent-placeholder
              hint="TURN キーと一緒に表示される API トークン。保存後は表示しません"
              persistent-hint
            />
          </template>
          <v-textarea v-model="form.note" label="メモ（任意）" rows="2" auto-grow />
          <v-checkbox
            v-model="form.is_default"
            label="既定のサーバにする"
            hint="サーバを選んでいないルームと、ルームを割り当てていない端末が使います。既定にできるのは 1 つだけです"
            persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!canSave" @click="save">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="deleteOpen" title="サーバを削除" confirm-text="削除" danger :busy="saving" @confirm="confirmDelete">
      「{{ deleteTarget?.name }}」を削除します。このサーバを使うルームがあるときは削除できません。
      <template v-if="deleteTarget?.is_default">
        <br />これは既定のサーバです。削除すると、サーバを選んでいないルームはつなげなくなります（別のサーバを既定にしてください）。
      </template>
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MasterToolbar from '@/components/masters/MasterToolbar.vue'
import { useServersMaster } from '@/composables/useMasters'
import type { Server, ServerInput, ServerKind } from '@/types'

const kindItems: { title: string; value: ServerKind }[] = [
  { title: 'Ayame', value: 'ayame' },
  { title: 'Ayame + Cloudflare TURN', value: 'cloudflare' },
]

function kindLabel(kind: ServerKind): string {
  return kind === 'cloudflare' ? 'Cloudflare TURN' : 'Ayame'
}

const headers = [
  { title: 'サーバ名', key: 'name' },
  { title: '種類', key: 'kind' },
  { title: 'シグナリングURL', key: 'signaling_url' },
  { title: 'ルーム', key: 'room_count', align: 'end' as const },
  { title: 'メモ', key: 'note' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const servers = useServersMaster()
const search = ref('')
const error = ref<string | null>(null)

const editOpen = ref(false)
const editing = ref<Server | null>(null)
const form = reactive<ServerInput>({
  name: '', signaling_url: '', kind: 'ayame', turn_key_id: '', turn_api_token: '', note: '', is_default: false,
})
const formError = ref<string | null>(null)
const saving = ref(false)

const canSave = computed(() => {
  if (!form.name || !form.signaling_url) return false
  if (form.kind !== 'cloudflare') return true
  return !!form.turn_key_id && (!!form.turn_api_token || !!editing.value?.turn_api_token_set)
})

function openEdit(server: Server | null): void {
  editing.value = server
  formError.value = null
  Object.assign(form, {
    name: server?.name ?? '',
    signaling_url: server?.signaling_url ?? '',
    kind: server?.kind ?? 'ayame',
    turn_key_id: server?.turn_key_id ?? '',
    turn_api_token: '',
    note: server?.note ?? '',
    // 最初の 1 台は既定にしておく（サーバを選ばないルームがそのまま使える）
    is_default: server ? server.is_default : servers.items.value.length === 0,
  })
  editOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    await servers.save({ ...form }, editing.value?.id)
    editOpen.value = false
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

async function makeDefault(server: Server): Promise<void> {
  try {
    await servers.save({
      name: server.name, signaling_url: server.signaling_url, kind: server.kind, turn_key_id: server.turn_key_id,
      turn_api_token: '', note: server.note, is_default: true,
    }, server.id)
  } catch (e) {
    error.value = (e as Error).message
  }
}

const deleteOpen = ref(false)
const deleteTarget = ref<Server | null>(null)

function askDelete(server: Server): void {
  deleteTarget.value = server
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await servers.remove(deleteTarget.value.id)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
    deleteOpen.value = false
  }
}

onMounted(async () => {
  await servers.fetchAll()
  error.value = servers.error.value
})
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
code { font-family: var(--font-mono); font-size: var(--fs-xs); }
.default-chip { margin-left: var(--sp-1); }
</style>
