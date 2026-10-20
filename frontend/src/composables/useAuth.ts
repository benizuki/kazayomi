import { computed, readonly, ref } from 'vue'
import type { AuthMode, GroupRef, GroupRole, MeResponse, PendingInvitation, Permissions, Role } from '@/types'

// モジュールスコープに置くことで、useAuth() をどこから何度呼んでも同じ状態を指す。
const me = ref<MeResponse | null>(null)
const loaded = ref(false)

const NO_PERMISSIONS: Permissions = {
  can_view: false, can_edit: false, can_manage_devices: false, can_manage_users: false, can_manage_members: false,
}

// グループでの役割の権限（backend の domain/access.py と同じ）
const GROUP_ROLE_PERMISSIONS: Record<GroupRole, Permissions> = {
  owner:  { can_view: true, can_edit: true,  can_manage_devices: true,  can_manage_users: false, can_manage_members: true },
  editor: { can_view: true, can_edit: true,  can_manage_devices: false, can_manage_users: false, can_manage_members: false },
  viewer: { can_view: true, can_edit: false, can_manage_devices: false, can_manage_users: false, can_manage_members: false },
}
const GLOBAL_KEYS: (keyof Permissions)[] = ['can_manage_devices', 'can_manage_users', 'can_manage_members']

/** ログイン画面へ移る。戻ってきたときに、いま開いていた画面に戻れるようにする。 */
export function goToLogin(): void {
  const next = window.location.pathname + window.location.search
  window.location.href = `/login?next=${encodeURIComponent(next)}`
}

export function useAuth() {
  async function fetchMe(): Promise<void> {
    try {
      const res = await fetch('/api/me')
      // 401 はセッション切れ。SPA 内で握らず、素直にログイン画面へ返す
      if (res.status === 401) {
        goToLogin()
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      me.value = await res.json() as MeResponse
      loaded.value = true
    } catch {
      // サーバーに届かないときはログイン画面にしても直らないので、その場でやり直せるようにする
      loaded.value = true
    }
  }

  /**
   * そのグループで key の権限を持っているか。ボタンの出し分けに使う（API 側でも同じ判定をしている）。
   * 全体のロールとグループでの役割の、強いほう
   */
  function canIn(groupId: string | null | undefined, key: keyof Permissions): boolean {
    const current = me.value
    if (!current) return false
    if (current.global_permissions[key] && GLOBAL_KEYS.includes(key)) return true
    if (!groupId) return false
    const member = current.all_groups || groupId in current.group_roles
    if (!member) return false
    const role = current.group_roles[groupId]
    return current.global_permissions[key] || (!!role && GROUP_ROLE_PERMISSIONS[role][key])
  }

  /** 招待を受けた・断ったあとに、所属グループと招待を読み直す */
  async function respondInvitation(id: string, accept: boolean): Promise<void> {
    const res = await fetch(`/api/invitations/${encodeURIComponent(id)}${accept ? '/accept' : ''}`, {
      method: accept ? 'POST' : 'DELETE',
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { error?: string } | null
      throw new Error(body?.error ?? `HTTP ${res.status}`)
    }
    await fetchMe()
  }

  async function logout(): Promise<void> {
    const res = await fetch('/logout', { method: 'POST' }).catch(() => null)
    const body = await res?.json().catch(() => null) as { login_url?: string } | null
    window.location.href = body?.login_url ?? '/login'
  }

  return {
    me:          readonly(me),
    loaded:      readonly(loaded),
    user:        computed(() => me.value?.user ?? null),
    role:        computed<Role | null>(() => me.value?.role ?? null),
    permissions: computed<Permissions>(() => me.value?.permissions ?? NO_PERMISSIONS),
    groups:      computed<GroupRef[]>(() => me.value?.groups ?? []),
    authMode:    computed<AuthMode | null>(() => me.value?.auth_mode ?? null),
    globalPermissions: computed<Permissions>(() => me.value?.global_permissions ?? NO_PERMISSIONS),
    /** ユーザーのマスターにいない人。使えるのは一時的なルームだけ */
    isGuest:     computed(() => me.value?.guest ?? false),
    /** ゲストで、利用規約への同意がまだ */
    consentRequired: computed(() => !!me.value?.guest && !!me.value.consent?.required),
    invitations: computed<PendingInvitation[]>(() => me.value?.invitations ?? []),
    canIn,
    fetchMe,
    respondInvitation,
    logout,
  }
}
