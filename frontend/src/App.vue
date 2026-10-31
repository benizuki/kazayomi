<template>
  <v-app>
    <!-- ログインを省いている間は常時バナーを出す。
         「ローカルだから」で消すと、そのまま気付かず公開する事故が起きる。 -->
    <div v-if="authMode === 'dev-bypass'" class="dev-banner">
      <v-icon icon="mdi-shield-off-outline" size="16" />
      <span>開発モード：Google ログインを省略しています（{{ user?.email }} / {{ role }}）。この状態で公開しないでください。</span>
    </div>

    <v-app-bar density="compact" flat border="b" color="surface" :style="authMode === 'dev-bypass' ? 'top: 30px' : undefined">
      <div class="brand">
        <v-icon icon="mdi-weather-windy" class="brand__icon" />
        <span class="brand__name">kazayomi</span>
      </div>
      <nav v-if="me" class="nav">
        <v-btn
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :exact="item.to === '/'"
          :prepend-icon="item.icon"
          variant="text"
          :active="isActive(item.to)"
          class="nav__btn"
        >{{ item.label }}</v-btn>
      </nav>
      <v-spacer />
      <!-- 自分あての招待。ログイン済みの人は、ここで参加するかを選ぶ -->
      <v-menu v-if="invitations.length" location="bottom end" :close-on-content-click="false">
        <template #activator="{ props: menuProps }">
          <v-btn v-bind="menuProps" icon variant="text" :aria-label="`グループへの招待 ${invitations.length} 件`">
            <v-badge :content="invitations.length" color="warning">
              <v-icon icon="mdi-email-outline" />
            </v-badge>
          </v-btn>
        </template>
        <v-card min-width="300" max-width="380">
          <div class="invites">
            <div class="field-label">グループへの招待</div>
            <p v-if="inviteError" class="tip tip--compact tip--warn">{{ inviteError }}</p>
            <div v-for="invite in invitations" :key="invite.id" class="invite">
              <div class="invite__text">
                <div class="invite__group">{{ invite.group_name }}</div>
                <div class="meta-text">{{ GROUP_ROLE_LABELS[invite.role] }}として招待されています</div>
              </div>
              <v-btn size="small" variant="text" :disabled="inviteBusy" @click="respond(invite.id, false)">断る</v-btn>
              <v-btn size="small" color="primary" :loading="inviteBusy" @click="respond(invite.id, true)">参加する</v-btn>
            </div>
          </div>
        </v-card>
      </v-menu>
      <ThemeToggle />
      <v-menu v-if="user" location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn v-bind="menuProps" variant="text" class="user-btn" :aria-label="`${user.name} のメニュー`">
            <v-avatar size="26" class="user-btn__avatar">
              <v-img v-if="user.picture" :src="user.picture" alt="" />
              <span v-else>{{ initial }}</span>
            </v-avatar>
          </v-btn>
        </template>
        <v-card min-width="240">
          <div class="user-card">
            <div class="user-card__name">{{ user.name }}</div>
            <div v-if="user.email" class="meta-text">{{ user.email }}</div>
            <!-- ゲスト。名前もメールアドレスも持っていない -->
            <div v-else class="meta-text">ゲストとして使っています（ニックネームはこのブラウザにだけ持ち、サーバには保存していません）</div>
            <div v-if="user.email" class="user-card__chips">
              <span class="chip chip--sm chip--brand">{{ roleLabel }}</span>
              <span v-for="g in groups" :key="g.id" class="chip chip--sm" :class="me?.group_roles[g.id] === 'owner' ? 'chip--info' : ''">
                {{ g.name }}<template v-if="me?.group_roles[g.id] === 'owner'">（管理）</template>
              </span>
            </div>
          </div>
          <v-divider />
          <v-list density="compact">
            <v-list-item prepend-icon="mdi-logout" title="ログアウト" @click="logout" />
          </v-list>
        </v-card>
      </v-menu>
    </v-app-bar>

    <!-- --app-top は上に固定した帯（開発モードの警告＋ツールバー）の高さ。画面いっぱいに使う画面が、高さの計算に使う -->
    <v-main :style="authMode === 'dev-bypass' ? 'padding-top: 78px; --app-top: 78px' : undefined">
      <router-view v-if="me" />
      <div v-else-if="loaded" class="empty-state">
        <v-icon icon="mdi-cloud-off-outline" size="40" />
        <p>サーバーに接続できません。サーバーの状態を確認して、画面を開き直してください。</p>
        <v-btn variant="outlined" @click="fetchMe">やり直す</v-btn>
      </div>
      <v-progress-linear v-else indeterminate color="primary" />
    </v-main>
  </v-app>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from 'vuetify'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAuth } from '@/composables/useAuth'
import { useThemeMode } from '@/composables/useThemeMode'

// tokens.css（CSS 変数）と Vuetify のテーマを合わせる。
const theme = useTheme()
const { effectiveTheme } = useThemeMode()
watch(effectiveTheme, (next) => { theme.change(next) }, { immediate: true })

const route = useRoute()
const { me, loaded, user, role, permissions, groups, authMode, invitations,
  fetchMe, respondInvitation, logout } = useAuth()

const GROUP_ROLE_LABELS = { owner: 'グループ管理者', editor: '編集者', viewer: '閲覧者' } as const
const inviteBusy = ref(false)
const inviteError = ref<string | null>(null)

async function respond(id: string, accept: boolean): Promise<void> {
  inviteBusy.value = true
  inviteError.value = null
  try {
    await respondInvitation(id, accept)
  } catch (e) {
    inviteError.value = (e as Error).message
  } finally {
    inviteBusy.value = false
  }
}

const ROLE_LABELS = { admin: '管理者', device_admin: 'デバイス管理者', power: '編集者', user: '閲覧者' } as const
const roleLabel = computed(() => (role.value ? ROLE_LABELS[role.value] : ''))
const initial = computed(() => (user.value?.name || user.value?.email || '?').slice(0, 1).toUpperCase())

const navItems = computed(() => {
  const items = [
    { to: '/',        label: 'ルーム',     icon: 'mdi-cctv' },
    { to: '/multi',   label: 'マルチビュー', icon: 'mdi-view-grid-outline' },
    { to: '/library', label: 'ライブラリ',   icon: 'mdi-image-multiple-outline' },
    { to: '/albums',  label: 'アルバム',     icon: 'mdi-folder-star-outline' },
  ]
  // 使えない機能はボタンごと隠す（API 側でも同じ権限を確かめている）
  // グループ管理者も、自分のグループのメンバー・ルーム・デバイスを扱うのでマスターを開ける
  if (permissions.value.can_manage_users || permissions.value.can_manage_devices || permissions.value.can_manage_members) {
    items.push({ to: '/masters', label: 'マスター', icon: 'mdi-database-cog-outline' })
  }
  return items
})

function isActive(to: string): boolean {
  if (to === '/') return route.path === '/' || route.path.startsWith('/view/')
  return route.path.startsWith(to)
}

onMounted(fetchMe)
</script>

<style scoped>
.dev-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1010;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  height: 30px;
  color: var(--text-warn);
  background: var(--surface-warn);
  border-bottom: 1px solid var(--border-warn);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 0 var(--sp-4);
}
.brand__icon { color: var(--text-brand); }
.brand__name {
  color: var(--ink-1);
  font-size: var(--fs-lg);
  font-weight: var(--fw-bold);
  letter-spacing: 0.02em;
}
.nav { display: flex; gap: var(--sp-1); }
.nav__btn { font-size: var(--fs-sm); color: var(--ink-3); }
.invites { display: flex; flex-direction: column; gap: var(--sp-2); padding: var(--sp-3) var(--sp-4); }
.invite { display: flex; align-items: center; gap: var(--sp-1); }
.invite__text { flex: 1; min-width: 0; }
.invite__group { color: var(--ink-1); font-weight: var(--fw-medium); overflow-wrap: anywhere; }
.nav__btn.v-btn--active { color: var(--text-brand); background: var(--surface-accent); }
.nav__btn.v-btn--active :deep(.v-btn__overlay) { opacity: 0; }
.user-btn { min-width: 0; padding: 0 var(--sp-2); }
.user-btn__avatar { color: var(--text-on-solid); background: var(--surface-accent-solid); font-size: var(--fs-sm); font-weight: var(--fw-bold); }
.user-card { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-4); }
.user-card__name { color: var(--ink-1); font-weight: var(--fw-bold); }
.user-card__chips { display: flex; flex-wrap: wrap; gap: var(--sp-1); margin-top: var(--sp-1); }
</style>
