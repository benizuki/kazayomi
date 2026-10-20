<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">マスター</h1>
        <p class="page-lead">{{ lead }}</p>
      </div>
    </header>

    <v-tabs v-model="tab" color="primary" density="compact" class="tabs">
      <v-tab v-for="item in tabs" :key="item.key" :value="item.key" :prepend-icon="item.icon">{{ item.label }}</v-tab>
    </v-tabs>

    <div v-if="tabs.length === 0" class="empty-state">
      <v-icon icon="mdi-lock-outline" size="40" />
      <p>マスターを編集する権限がありません。</p>
    </div>
    <MembersTab v-else-if="tab === 'members'" />
    <UsersTab v-else-if="tab === 'users'" />
    <GroupsTab v-else-if="tab === 'groups'" />
    <ServersTab v-else-if="tab === 'servers'" />
    <RoomsTab v-else-if="tab === 'rooms'" />
    <DevicesTab v-else-if="tab === 'devices'" />
    <SettingsTab v-else-if="tab === 'settings'" />
    <AuditTab v-else-if="tab === 'audit'" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuditTab from '@/components/masters/AuditTab.vue'
import RoomsTab from '@/components/masters/RoomsTab.vue'
import DevicesTab from '@/components/masters/DevicesTab.vue'
import GroupsTab from '@/components/masters/GroupsTab.vue'
import MembersTab from '@/components/masters/MembersTab.vue'
import ServersTab from '@/components/masters/ServersTab.vue'
import SettingsTab from '@/components/masters/SettingsTab.vue'
import UsersTab from '@/components/masters/UsersTab.vue'
import { useAuth } from '@/composables/useAuth'

const route = useRoute()
const router = useRouter()
const { permissions, globalPermissions } = useAuth()

// scope: global はアプリ全体のロールで持っているときだけ、any はどれかのグループで持っていれば出す
// （グループ管理者は、自分のグループのメンバー・ルーム・デバイスだけを扱う）
const ALL_TABS = [
  { key: 'members',  label: 'メンバー',   icon: 'mdi-account-group-outline',    perm: 'can_manage_members', scope: 'any',
    lead: 'グループのメンバーと招待です。招待した人は、そのメールアドレスの Google アカウントでログインすると参加できます。' },
  { key: 'users',    label: 'ユーザー',   icon: 'mdi-account-multiple-outline', perm: 'can_manage_users',   scope: 'global',
    lead: 'ログインできる人と、そのロール・所属グループです。' },
  { key: 'groups',   label: 'グループ',   icon: 'mdi-folder-account-outline',   perm: 'can_manage_users',   scope: 'global',
    lead: 'ルーム・画像・アルバムを見られる範囲を分ける単位です。グループを作れるのはアプリの管理者だけです。作ったら、メンバー タブで最初のグループ管理者を招待します。' },
  { key: 'servers',  label: 'サーバ',     icon: 'mdi-server-network',           perm: 'can_manage_devices', scope: 'global',
    lead: 'Ayame のシグナリングサーバです。ルームはどれか 1 つのサーバを使います。' },
  { key: 'rooms',    label: 'ルーム',     icon: 'mdi-cctv',                     perm: 'can_manage_devices', scope: 'any',
    lead: 'Kazami のルームです。グループに属し、そのグループのユーザーにだけ見えます。' },
  { key: 'devices',  label: 'デバイス',   icon: 'mdi-cellphone-link',           perm: 'can_manage_devices', scope: 'any',
    lead: 'Kazami 端末です。登録 QR で端末を登録し、つながるルームを割り当てます。' },
  { key: 'settings', label: '設定',       icon: 'mdi-cog-outline',              perm: 'can_manage_users',   scope: 'global',
    lead: 'アプリ全体の設定です。ゲストの受け付けと、新しく作られるグループの容量を決めます。' },
  { key: 'audit',    label: '監査ログ',   icon: 'mdi-clipboard-text-clock-outline', perm: 'can_manage_users', scope: 'global',
    lead: 'ログインと、マスター・画像・アルバムの変更の記録です。' },
] as const

const tabs = computed(() => ALL_TABS.filter((t) => (t.scope === 'global' ? globalPermissions : permissions).value[t.perm]))

// タブは URL に持つ（/masters/rooms）。ほかの画面からタブを指定して開けるようにするため
const tab = computed({
  get: () => {
    const requested = String(route.params.tab ?? '')
    return tabs.value.some((t) => t.key === requested) ? requested : tabs.value[0]?.key ?? ''
  },
  set: (value: string) => { void router.replace(`/masters/${value}`) },
})
const lead = computed(() => ALL_TABS.find((t) => t.key === tab.value)?.lead ?? '')
</script>

<style scoped>
.tabs { margin-bottom: var(--sp-4); border-bottom: 1px solid var(--border-default); }
</style>
