<template>
  <div>
    <MasterToolbar v-model="search" placeholder="誰が・何を・対象で絞り込み">
      <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">更新</v-btn>
    </MasterToolbar>
    <v-alert v-if="error" type="error" class="mb-3">{{ error }}</v-alert>
    <p class="tip tip--compact mb-3">
      <v-icon icon="mdi-shield-account-outline" />
      <span>監査ログには生のメールアドレスが入るため、管理者だけが見られます。新しい順に最大 500 件です。</span>
    </p>

    <v-data-table
      :headers="headers"
      :items="logs"
      :loading="loading"
      :search="search"
      no-data-text="記録はまだありません"
      loading-text="読み込み中…"
      items-per-page-text="表示件数"
      density="compact"
    >
      <template #item.timestamp="{ item }"><span class="numeric">{{ formatDateTime(item.timestamp) }}</span></template>
      <template #item.event="{ item }">
        <span class="chip chip--sm" :class="item.outcome === 'success' ? '' : 'chip--danger'">{{ EVENT_LABELS[item.event] ?? item.event }}</span>
      </template>
      <template #item.detail="{ item }"><span class="meta-text detail">{{ item.detail }}</span></template>
    </v-data-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import MasterToolbar from '@/components/masters/MasterToolbar.vue'
import { formatDateTime } from '@/composables/format'
import { fetchAuditLogs } from '@/composables/useMasters'
import type { AuditLog } from '@/types'

const EVENT_LABELS: Record<string, string> = {
  'auth.login': 'ログイン',
  'user.create': 'ユーザー追加', 'user.update': 'ユーザー変更', 'user.delete': 'ユーザー削除',
  'group.create': 'グループ追加', 'group.update': 'グループ変更', 'group.delete': 'グループ削除',
  'server.create': 'サーバ追加', 'server.update': 'サーバ変更', 'server.delete': 'サーバ削除',
  'room.create': 'ルーム追加', 'room.update': 'ルーム変更', 'room.delete': 'ルーム削除',
  // 「チャネル」を「ルーム」に改める前に記録したもの
  'channel.create': 'ルーム追加', 'channel.update': 'ルーム変更', 'channel.delete': 'ルーム削除',
  'device.create': 'デバイス追加', 'device.update': 'デバイス変更', 'device.delete': 'デバイス削除',
  'device.enrollment.issue': '登録 QR 発行', 'device.enrollment.clear': '端末登録の解除', 'device.enroll': '端末登録',
  'image.delete': '画像削除', 'album.delete': 'アルバム削除',
}

const headers = [
  { title: '日時', key: 'timestamp' },
  { title: '誰が', key: 'email' },
  { title: '何を', key: 'event' },
  { title: '対象', key: 'target' },
  { title: '詳細', key: 'detail', sortable: false },
]

const logs = ref<AuditLog[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const search = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    logs.value = await fetchAuditLogs()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.detail { display: inline-block; max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
</style>
