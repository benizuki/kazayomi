<template>
  <div>
    <MasterToolbar v-model="search" add-label="デバイスを追加" placeholder="名前・ルーム・デバイスIDで絞り込み" @add="openEdit(null)" />
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>
    <p class="tip tip--compact mb-3">
      <v-icon icon="mdi-information-outline" />
      <span>デバイスを追加して「登録 QR」を発行し、Kazami の設定 › 端末登録 で読み取ります。登録した端末は、ここで割り当てたルームに自動でつながります。</span>
    </p>

    <v-data-table
      :headers="headers"
      :items="devices.items.value"
      :loading="devices.loading.value"
      :search="search"
      no-data-text="デバイスがありません"
      loading-text="読み込み中…"
      items-per-page-text="表示件数"
    >
      <template #item.name="{ item }">
        <div class="cell-main">{{ item.name }}</div>
        <div v-if="item.device_id" class="meta-text"><code>{{ item.device_id }}</code></div>
      </template>
      <template #item.room_name="{ item }">
        <template v-if="item.room_id">
          <div>{{ item.room_name }}</div>
          <div class="meta-text">{{ item.group_name }} ・ <code>{{ item.ayame_room_id }}</code></div>
        </template>
        <span v-else class="chip chip--sm chip--warn">ルーム未設定</span>
      </template>
      <template #item.enrolled="{ item }">
        <span class="chip chip--sm chip--pill" :class="item.enrolled ? 'chip--brand' : 'chip--warn'">{{ item.enrolled ? '登録済み' : '未登録' }}</span>
      </template>
      <template #item.last_seen_at="{ item }">
        <div class="meta-text">{{ item.last_seen_at ? formatDateTime(item.last_seen_at) : '—' }}</div>
        <div v-if="item.last_ip" class="meta-text">{{ item.last_ip }}</div>
      </template>
      <template #item.actions="{ item }">
        <v-btn size="small" variant="tonal" prepend-icon="mdi-qrcode" @click="openQr(item)">登録 QR</v-btn>
        <v-btn icon="mdi-pencil-outline" variant="text" size="small" aria-label="編集" @click="openEdit(item)" />
        <v-menu location="bottom end">
          <template #activator="{ props: menuProps }">
            <v-btn v-bind="menuProps" icon="mdi-dots-vertical" variant="text" size="small" aria-label="その他の操作" />
          </template>
          <v-list density="compact">
            <v-list-item :disabled="!item.enrolled" prepend-icon="mdi-link-variant-off" title="登録を外す" @click="askClear(item)" />
            <v-list-item prepend-icon="mdi-delete-outline" title="削除" class="text-error" @click="askDelete(item)" />
          </v-list>
        </v-menu>
      </template>
    </v-data-table>

    <!-- 追加・編集 -->
    <v-dialog v-model="editOpen" max-width="520">
      <v-card>
        <v-card-title class="dialog-title">{{ editing ? 'デバイスを編集' : 'デバイスを追加' }}</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <v-text-field v-model="form.name" label="デバイス名（例: ライン1 の iPhone）" autofocus />
          <v-select
            v-model="form.room_id"
            :items="roomItems"
            label="ルーム"
            hint="この端末がつながるルーム。変えると、端末の次の起動から新しいルームにつながります"
            persistent-hint
          />
          <v-textarea v-model="form.note" label="メモ（任意）" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">キャンセル</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!form.name || (!form.room_id && !globalPermissions.can_manage_devices)" @click="save">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 登録 QR -->
    <v-dialog v-model="qrOpen" max-width="560">
      <v-card>
        <v-card-title class="dialog-title">登録 QR（{{ qrDevice?.name }}）</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="qrError" type="error">{{ qrError }}</v-alert>
          <p v-if="qrDevice?.enrolled" class="tip tip--compact tip--warn">
            <v-icon icon="mdi-alert-outline" />
            <span>このデバイスは登録済みです。別の端末で読み取ると、そちらに置き換わります（元の端末は認証できなくなります）。</span>
          </p>
          <v-text-field
            v-model="apiUrl"
            label="kazayomi の URL（Kazami から届くもの）"
            hint="iPhone から開ける URL にします。localhost は iPhone 自身を指すので使えません（シミュレータは可）"
            persistent-hint
          />
          <div class="qr">
            <img v-if="qrImage" :src="qrImage" alt="端末登録用の QR コード" class="qr__img">
            <v-progress-circular v-else-if="!qrError" indeterminate />
          </div>
          <p class="qr__expiry meta-text">
            <template v-if="remaining > 0">有効期限まで あと {{ Math.floor(remaining / 60) }}分{{ String(remaining % 60).padStart(2, '0') }}秒（1 回だけ使えます）</template>
            <template v-else-if="ticket">期限が切れました。「発行し直す」を押してください。</template>
          </p>
          <details class="qr__raw">
            <summary class="meta-text">QR の中身（シミュレータでは、これを貼り付けて登録できます）</summary>
            <code>{{ qrText }}</code>
            <v-btn size="small" variant="text" prepend-icon="mdi-content-copy" @click="copyQrText">コピー</v-btn>
          </details>
        </v-card-text>
        <v-card-actions>
          <v-btn variant="text" prepend-icon="mdi-refresh" :loading="issuing" @click="issue">発行し直す</v-btn>
          <v-spacer />
          <v-btn color="primary" @click="closeQr">閉じる</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="clearOpen" title="登録を外す" confirm-text="外す" danger :busy="saving" @confirm="confirmClear">
      「{{ target?.name }}」の端末登録を外します。この端末は次の接続からルームに入れなくなり、使うには QR で登録し直す必要があります（端末をなくしたとき・入れ替えるときに使います）。
    </ConfirmDialog>
    <ConfirmDialog v-model="deleteOpen" title="デバイスを削除" confirm-text="削除" danger :busy="saving" @confirm="confirmDelete">
      「{{ target?.name }}」を削除します。登録済みの端末は認証できなくなります。
    </ConfirmDialog>
    <v-snackbar v-model="snackbar" :timeout="2000" location="bottom right">{{ snackbarText }}</v-snackbar>
  </div>
</template>

<script setup lang="ts">
import QRCode from 'qrcode'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MasterToolbar from '@/components/masters/MasterToolbar.vue'
import { copyToClipboard } from '@/composables/clipboard'
import { formatDateTime } from '@/composables/format'
import { useAuth } from '@/composables/useAuth'
import { clearEnrollment, issueEnrollment, useRoomsMaster, useDevicesMaster } from '@/composables/useMasters'
import { useStoredRef } from '@/composables/useStoredRef'
import type { Device, DeviceInput, EnrollmentTicket } from '@/types'

const headers = [
  { title: 'デバイス', key: 'name' },
  { title: 'ルーム', key: 'room_name' },
  { title: '登録', key: 'enrolled' },
  { title: '最終接続', key: 'last_seen_at' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const devices = useDevicesMaster()
const rooms = useRoomsMaster()
const search = ref('')
const error = ref<string | null>(null)
const snackbar = ref(false)
const snackbarText = ref('')

// ルームのない端末は、アプリ全体のデバイス管理者だけが扱える（グループ管理者は自分のグループのルームを選ぶ）
const { globalPermissions } = useAuth()
const roomItems = computed(() => [
  ...(globalPermissions.value.can_manage_devices ? [{ title: '未設定（端末は待機します）', value: null }] : []),
  ...rooms.items.value.map((c) => ({ title: `${c.name}（${c.group_name} / ${c.ayame_room_id}）`, value: c.id })),
])

// ── 追加・編集 ────────────────────────────────────
const editOpen = ref(false)
const editing = ref<Device | null>(null)
const form = reactive<DeviceInput>({ name: '', room_id: null, note: '' })
const formError = ref<string | null>(null)
const saving = ref(false)

function openEdit(device: Device | null): void {
  editing.value = device
  formError.value = null
  // グループ管理者はルームなしで作れないので、最初のルームを選んでおく
  const defaultRoom = globalPermissions.value.can_manage_devices ? null : rooms.items.value[0]?.id ?? null
  Object.assign(form, { name: device?.name ?? '', room_id: device ? device.room_id : defaultRoom, note: device?.note ?? '' })
  editOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    const saved = await devices.save({ ...form }, editing.value?.id)
    editOpen.value = false
    // 追加した直後は、そのまま登録 QR を出す（次にすることがそれなので）
    if (!editing.value) openQr(saved)
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

// ── 登録 QR ───────────────────────────────────────
const qrOpen = ref(false)
const qrDevice = ref<Device | null>(null)
const ticket = ref<EnrollmentTicket | null>(null)
const qrImage = ref('')
const qrError = ref<string | null>(null)
const issuing = ref(false)
// 一度直した URL は次も使う（毎回 localhost に戻ると、実機で読めない QR を作ってしまう）
const apiUrl = useStoredRef('kazayomi.enrollApiUrl', '')
const now = ref(Date.now())
let clock: number | undefined

const remaining = computed(() => (ticket.value ? Math.max(0, Math.round((Date.parse(ticket.value.expires_at) - now.value) / 1000)) : 0))
// QR の中身は v / api / token / name。秘密は入れない
const qrText = computed(() => (ticket.value
  ? JSON.stringify({ v: 1, api: apiUrl.value.trim().replace(/\/$/, ''), token: ticket.value.token, name: ticket.value.name })
  : ''))

watch(qrText, async (text) => {
  qrImage.value = text ? await QRCode.toDataURL(text, { errorCorrectionLevel: 'M', margin: 2, width: 320 }) : ''
})

async function issue(): Promise<void> {
  if (!qrDevice.value) return
  issuing.value = true
  qrError.value = null
  try {
    ticket.value = await issueEnrollment(qrDevice.value.id)
    if (!apiUrl.value) apiUrl.value = ticket.value.suggested_api_url
  } catch (e) {
    qrError.value = (e as Error).message
  } finally {
    issuing.value = false
  }
}

function openQr(device: Device): void {
  qrDevice.value = device
  ticket.value = null
  qrImage.value = ''
  qrOpen.value = true
  window.clearInterval(clock)
  clock = window.setInterval(() => { now.value = Date.now() }, 1000)
  void issue()
}

function closeQr(): void {
  qrOpen.value = false
  window.clearInterval(clock)
  // 読み取られたかどうかを一覧に出すため、閉じたら取り直す
  void devices.fetchAll()
}

async function copyQrText(): Promise<void> {
  snackbarText.value = await copyToClipboard(qrText.value) ? 'コピーしました' : 'コピーできませんでした。上の文字を選んでコピーしてください'
  snackbar.value = true
}

onBeforeUnmount(() => window.clearInterval(clock))

// ── 登録解除・削除 ────────────────────────────────
const target = ref<Device | null>(null)
const clearOpen = ref(false)
const deleteOpen = ref(false)

function askClear(device: Device): void {
  target.value = device
  clearOpen.value = true
}

function askDelete(device: Device): void {
  target.value = device
  deleteOpen.value = true
}

async function confirmClear(): Promise<void> {
  if (!target.value) return
  saving.value = true
  try {
    await clearEnrollment(target.value.id)
    await devices.fetchAll()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
    clearOpen.value = false
  }
}

async function confirmDelete(): Promise<void> {
  if (!target.value) return
  saving.value = true
  try {
    await devices.remove(target.value.id)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
    deleteOpen.value = false
  }
}

onMounted(async () => {
  await Promise.all([devices.fetchAll(), rooms.fetchAll()])
  error.value = devices.error.value ?? rooms.error.value
})
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
.cell-main { color: var(--ink-1); font-weight: var(--fw-medium); }
code { font-family: var(--font-mono); font-size: var(--fs-xs); word-break: break-all; }
.qr { display: grid; place-items: center; min-height: 320px; }
.qr__img { width: 320px; height: 320px; border-radius: var(--radius-sm); background: white; image-rendering: pixelated; }
.qr__expiry { margin: 0; text-align: center; }
.qr__raw summary { cursor: pointer; }
.qr__raw code { display: block; margin: var(--sp-2) 0; padding: var(--sp-2); border-radius: var(--radius-sm); background: var(--surface-muted); }
</style>
