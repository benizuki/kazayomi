<template>
  <div>
    <div class="master-toolbar">
      <v-select
        v-if="managed.length > 1"
        v-model="groupId"
        :items="managed"
        item-title="name"
        item-value="id"
        label="グループ"
        density="compact"
        hide-details
        class="members__group"
      />
      <div v-else-if="currentGroup" class="members__single">
        <v-icon icon="mdi-account-group-outline" size="18" />
        <span class="cell-main">{{ currentGroup.name }}</span>
      </div>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-email-plus-outline" :disabled="!groupId" @click="openInvite">メンバーを招待</v-btn>
    </div>
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>

    <div v-if="!loadingGroups && managed.length === 0" class="empty-state">
      <v-icon icon="mdi-account-group-outline" size="40" />
      <p>メンバーを管理できるグループがありません。</p>
    </div>

    <template v-else>
      <!-- 画像の置き場の使用量。上限はアプリの管理者が決める -->
      <section v-if="currentGroup" class="panel usage-panel" aria-labelledby="usage-title">
        <div class="usage-panel__head">
          <h2 id="usage-title" class="section-title">容量</h2>
          <span class="meta-text">画像 {{ currentGroup.image_count }} 枚</span>
        </div>
        <UsageMeter :usage="currentGroup.usage_bytes" :quota="currentGroup.quota_bytes" />
        <p v-if="currentGroup.quota_bytes != null && currentGroup.usage_bytes >= currentGroup.quota_bytes" class="tip tip--compact tip--warn">
          上限に達しているため、このグループには画像を保存できません。不要な画像を消すか、アプリの管理者に上限を上げてもらってください。
        </p>
      </section>

      <!-- 招待中。本人がそのアドレスでログインすると参加できる -->
      <section v-if="invitations.length" class="panel invites" aria-labelledby="invites-title">
        <h2 id="invites-title" class="section-title">招待中</h2>
        <div v-for="invite in invitations" :key="invite.id" class="invite">
          <div class="invite__who">
            <div class="cell-main">{{ invite.email }}</div>
            <div class="meta-text">
              {{ GROUP_ROLE_LABELS[invite.role] }} ・
              <span v-if="invite.expired" class="invite__expired">期限切れ（招待し直してください）</span>
              <span v-else>{{ formatDateTime(invite.expires_at) }} まで</span>
            </div>
          </div>
          <v-btn variant="text" size="small" prepend-icon="mdi-content-copy" @click="copyInviteText(invite.email)">案内文をコピー</v-btn>
          <v-btn variant="text" size="small" color="error" @click="cancel(invite)">取り消す</v-btn>
        </div>
      </section>

      <v-data-table
        :headers="headers"
        :items="members"
        :loading="loading"
        item-value="user_id"
        no-data-text="メンバーがいません"
        loading-text="読み込み中…"
        items-per-page-text="表示件数"
      >
        <template #item.name="{ item }">
          <div class="cell-main">{{ item.name }}<span v-if="item.email === me?.user.email" class="meta-text">（自分）</span></div>
          <div class="meta-text">{{ item.email }}</div>
        </template>
        <template #item.role="{ item }">
          <v-select
            :model-value="item.role"
            :items="roleItems"
            density="compact"
            hide-details
            variant="plain"
            class="role-select"
            :aria-label="`${item.email} の役割`"
            @update:model-value="(role: GroupRole) => changeRole(item, role)"
          />
        </template>
        <template #item.enabled="{ item }">
          <span class="chip chip--sm chip--pill" :class="item.enabled ? 'chip--brand' : 'chip--danger'">{{ item.enabled ? '有効' : '無効' }}</span>
        </template>
        <template #item.last_login_at="{ item }">
          <span class="meta-text">{{ item.last_login_at ? formatDateTime(item.last_login_at) : '—' }}</span>
        </template>
        <template #item.actions="{ item }">
          <v-btn icon="mdi-account-remove-outline" variant="text" size="small" :aria-label="`${item.email} をグループから外す`" @click="askRemove(item)" />
        </template>
      </v-data-table>
      <p class="meta-text roles-hint">
        グループ管理者: メンバーの招待とルーム・デバイスの登録 ／ 編集者: タグ・アルバムの編集や画像の削除 ／ 閲覧者: 見て撮像するだけ
      </p>

      <!-- 中身ごと消すので、ほかの操作から離して置く。既定のグループは消せない -->
      <section v-if="currentGroup && currentGroup.id !== 'default'" class="panel danger" aria-labelledby="danger-title">
        <div class="danger__text">
          <h2 id="danger-title" class="section-title">グループを削除</h2>
          <p class="meta-text">ルーム・デバイス・画像・アルバムをすべて消します。このグループにしか入っていないメンバーは、アカウントも消します。元に戻せません。</p>
        </div>
        <v-btn color="error" variant="outlined" prepend-icon="mdi-delete-forever-outline" @click="openDelete">グループを削除</v-btn>
      </section>
    </template>

    <v-dialog v-model="inviteOpen" max-width="480">
      <v-card>
        <v-card-title class="dialog-title">メンバーを招待</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <template v-if="!invited">
            <v-text-field v-model="inviteForm.email" label="メールアドレス（Google アカウント）" type="email" autofocus />
            <v-select v-model="inviteForm.role" :items="roleItems" label="役割" />
            <p class="meta-text">招待は {{ INVITATION_DAYS }} 日間有効です。メールは送られないので、次の画面の案内文を本人に伝えてください。</p>
          </template>
          <template v-else>
            <p>{{ invited.email }} を招待しました。次の案内を本人に伝えてください。</p>
            <pre class="invite-text">{{ inviteText(invited.email) }}</pre>
          </template>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <template v-if="!invited">
            <v-btn variant="text" @click="inviteOpen = false">キャンセル</v-btn>
            <v-btn color="primary" :loading="saving" :disabled="!inviteForm.email" @click="invite">招待する</v-btn>
          </template>
          <template v-else>
            <v-btn variant="text" prepend-icon="mdi-content-copy" @click="copyInviteText(invited.email)">コピー</v-btn>
            <v-btn color="primary" @click="inviteOpen = false">閉じる</v-btn>
          </template>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog v-model="removeOpen" title="グループから外す" confirm-text="外す" danger :busy="saving" @confirm="confirmRemove">
      {{ removeTarget?.email }} を「{{ currentGroup?.name }}」から外します。このグループのルーム・画像・アルバムが見えなくなります（アカウントは残ります）。
    </ConfirmDialog>

    <v-dialog v-model="deleteOpen" max-width="500">
      <v-card>
        <v-card-title class="dialog-title">「{{ currentGroup?.name }}」を削除</v-card-title>
        <v-card-text class="form">
          <v-alert v-if="formError" type="error">{{ formError }}</v-alert>
          <p>次のものがすべて消えます。<strong>元に戻せません。</strong></p>
          <ul v-if="contents" class="contents">
            <li>ルーム {{ contents.rooms }} 件</li>
            <li>デバイス {{ contents.devices }} 台（端末は登録し直すまでつながらなくなります）</li>
            <li>画像 {{ contents.images }} 枚</li>
            <li>アルバム {{ contents.albums }} 件</li>
            <li v-if="contents.users_deleted">
              メンバーのうち {{ contents.users_deleted }} 人はアカウントも消えます（このグループにしか入っていない人。あなたも含まれるなら、削除のあとログアウトします）
            </li>
            <li v-if="contents.members - contents.users_deleted > 0">
              ほかの {{ contents.members - contents.users_deleted }} 人はこのグループから外れます（ほかのグループに入っている人などは、アカウントが残ります）
            </li>
            <li v-if="contents.invitations">招待 {{ contents.invitations }} 件</li>
          </ul>
          <v-progress-linear v-else indeterminate color="primary" />
          <p v-if="contents?.images" class="meta-text">画像を残したいときは、先にライブラリから ZIP で書き出してください。</p>
          <v-text-field v-model="confirmName" :label="`確認のため、グループ名「${currentGroup?.name}」を入力`" autocomplete="off" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteOpen = false">キャンセル</v-btn>
          <v-btn color="error" :loading="saving" :disabled="confirmName.trim() !== currentGroup?.name" @click="confirmDelete">削除する</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar" timeout="2500">{{ snackbarText }}</v-snackbar>
  </div>
</template>

<script setup lang="ts">
/**
 * グループ管理者が、自分のグループのメンバーを招待し、役割を変え、外す。
 * アプリの管理者は全グループを扱える。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import UsageMeter from '@/components/masters/UsageMeter.vue'
import { copyToClipboard } from '@/composables/clipboard'
import { formatDateTime } from '@/composables/format'
import { useAuth } from '@/composables/useAuth'
import { cancelInvitation, deleteGroup, fetchGroupContents, fetchManagedGroups, fetchMembers, inviteMember, removeMember, updateMember, type GroupContents } from '@/composables/useMasters'
import { useStoredRef } from '@/composables/useStoredRef'
import type { Group, GroupInvitation, GroupMember, GroupRole } from '@/types'

const GROUP_ROLE_LABELS: Record<GroupRole, string> = { owner: 'グループ管理者', editor: '編集者', viewer: '閲覧者' }
const roleItems = (Object.keys(GROUP_ROLE_LABELS) as GroupRole[]).map((value) => ({ title: GROUP_ROLE_LABELS[value], value }))
const INVITATION_DAYS = 14

const headers = [
  { title: 'メンバー', key: 'name' },
  { title: '役割', key: 'role', width: 200 },
  { title: '状態', key: 'enabled' },
  { title: '最終ログイン', key: 'last_login_at' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const { me, fetchMe, logout } = useAuth()
const managed = ref<Group[]>([])
const loadingGroups = ref(true)
const groupId = useStoredRef<string>('kazayomi.membersGroup', '')
const currentGroup = computed(() => managed.value.find((g) => g.id === groupId.value) ?? null)
const members = ref<GroupMember[]>([])
const invitations = ref<GroupInvitation[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const saving = ref(false)
const snackbar = ref(false)
const snackbarText = ref('')

async function load(): Promise<void> {
  if (!groupId.value) return
  loading.value = true
  try {
    const body = await fetchMembers(groupId.value)
    members.value = body.members
    invitations.value = body.invitations
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

watch(groupId, load)

// ── 招待 ─────────────────────────────────────────
const inviteOpen = ref(false)
const inviteForm = reactive<{ email: string; role: GroupRole }>({ email: '', role: 'editor' })
const invited = ref<GroupInvitation | null>(null)
const formError = ref<string | null>(null)

function openInvite(): void {
  Object.assign(inviteForm, { email: '', role: 'editor' })
  invited.value = null
  formError.value = null
  inviteOpen.value = true
}

async function invite(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    invited.value = await inviteMember(groupId.value, inviteForm.email.trim(), inviteForm.role)
    await load()
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

/** 本人に伝える案内。メールは送らないので、管理者がチャットなどで渡す */
function inviteText(email: string): string {
  const url = `${window.location.origin}/login`
  return `kazayomi の「${currentGroup.value?.name ?? ''}」に招待しました。\n`
    + `${url} を開き、${email} の Google アカウントでログインして「参加する」を押してください。\n`
    + `（招待は ${INVITATION_DAYS} 日間有効です）`
}

async function copyInviteText(email: string): Promise<void> {
  snackbarText.value = await copyToClipboard(inviteText(email)) ? '案内文をコピーしました' : 'コピーできませんでした。案内文を選んでコピーしてください'
  snackbar.value = true
}

async function cancel(invitation: GroupInvitation): Promise<void> {
  try {
    await cancelInvitation(groupId.value, invitation.id)
    await load()
  } catch (e) {
    error.value = (e as Error).message
  }
}

// ── 役割・外す ───────────────────────────────────
async function changeRole(member: GroupMember, role: GroupRole): Promise<void> {
  if (role === member.role) return
  try {
    await updateMember(groupId.value, member.user_id, role)
    // 自分の役割を変えたら、画面の権限も読み直す
    if (member.email === me.value?.user.email) await fetchMe()
  } catch (e) {
    error.value = (e as Error).message
  }
  await load()
}

const removeOpen = ref(false)
const removeTarget = ref<GroupMember | null>(null)

function askRemove(member: GroupMember): void {
  removeTarget.value = member
  removeOpen.value = true
}

async function confirmRemove(): Promise<void> {
  if (!removeTarget.value) return
  saving.value = true
  try {
    await removeMember(groupId.value, removeTarget.value.user_id)
    if (removeTarget.value.email === me.value?.user.email) await fetchMe()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    removeOpen.value = false
    saving.value = false
    await load()
  }
}

// ── グループの削除 ───────────────────────────────
const router = useRouter()
const deleteOpen = ref(false)
const contents = ref<GroupContents | null>(null)
const confirmName = ref('')

async function openDelete(): Promise<void> {
  contents.value = null
  confirmName.value = ''
  formError.value = null
  deleteOpen.value = true
  try {
    contents.value = await fetchGroupContents(groupId.value)
  } catch (e) {
    formError.value = (e as Error).message
  }
}

async function confirmDelete(): Promise<void> {
  saving.value = true
  formError.value = null
  try {
    const result = await deleteGroup(groupId.value, confirmName.value.trim())
    deleteOpen.value = false
    // 自分のアカウントも消えたので、ログイン画面に戻る
    if (result.self_deleted) {
      await logout()
      return
    }
    // 所属グループと権限が変わるので読み直し、ルームの一覧に戻る（マスターを開けなくなることがある）
    await fetchMe()
    await router.push('/')
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    managed.value = await fetchManagedGroups()
    if (!managed.value.some((g) => g.id === groupId.value)) groupId.value = managed.value[0]?.id ?? ''
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loadingGroups.value = false
  }
})
</script>

<style scoped>
.master-toolbar { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-3); }
.members__group { max-width: 320px; }
.members__single { display: flex; align-items: center; gap: var(--sp-2); color: var(--ink-2); }
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
.cell-main { color: var(--ink-1); font-weight: var(--fw-medium); }
.section-title { margin: 0 0 var(--sp-2); color: var(--ink-1); font-size: var(--fs-md); font-weight: var(--fw-medium); }
.invites { margin-bottom: var(--sp-4); }
.usage-panel { display: flex; flex-direction: column; gap: var(--sp-2); margin-bottom: var(--sp-4); }
.usage-panel__head { display: flex; align-items: baseline; justify-content: space-between; }
.usage-panel__head .section-title { margin: 0; }
.invite { display: flex; align-items: center; gap: var(--sp-2); padding: var(--sp-2) 0; border-top: 1px solid var(--border-default); }
.invite:first-of-type { border-top: 0; }
.invite__who { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.invite__expired { color: var(--text-danger); }
.invite-text {
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--radius-md);
  background: var(--surface-subtle);
  color: var(--ink-1);
  font-family: inherit;
  font-size: var(--fs-sm);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.role-select { max-width: 180px; }
.roles-hint { margin-top: var(--sp-2); }
.danger {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  margin-top: var(--sp-6);
  border-color: color-mix(in srgb, var(--text-danger) 35%, transparent);
}
.danger__text { flex: 1; min-width: 0; }
.danger__text p { margin: 0; }
.contents { margin: 0; padding-left: 1.2em; color: var(--ink-2); line-height: 1.9; }
@media (max-width: 600px) { .danger { flex-direction: column; align-items: stretch; } }
</style>
