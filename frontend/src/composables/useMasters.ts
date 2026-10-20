import { ref, type Ref } from 'vue'
import type { AppSettings, AuditLog, GroupInput, Room, RoomInput, Device, DeviceInput, EnrollmentTicket, Group, GroupInvitation, GroupMember, GroupRole, Server, ServerInput, UserInput, UserRecord } from '@/types'
import { getJson, sendJson } from './http'

/**
 * マスター 1 つぶんの一覧と編集。ユーザー・グループ・サーバ・ルームで同じ形にそろえる。
 * 更新系は「実行 → 再取得」で締める。楽観的更新より単純で、ズレが起きない。
 */
function useMaster<T extends { id: string }, I>(path: string) {
  const items = ref<T[]>([]) as Ref<T[]>
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await getJson<T[]>(path)
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function save(input: I, id?: string): Promise<T> {
    const saved = id
      ? await sendJson<T>(`${path}/${encodeURIComponent(id)}`, 'PUT', input)
      : await sendJson<T>(path, 'POST', input)
    await fetchAll()
    return saved
  }

  async function remove(id: string): Promise<void> {
    await sendJson(`${path}/${encodeURIComponent(id)}`, 'DELETE')
    await fetchAll()
  }

  return { items, loading, error, fetchAll, save, remove }
}

export const useUsersMaster = () => useMaster<UserRecord, UserInput>('/api/masters/users')
export const useGroupsMaster = () => useMaster<Group, GroupInput>('/api/masters/groups')

export function fetchAppSettings(): Promise<AppSettings> {
  return getJson<AppSettings>('/api/masters/settings')
}

export function saveAppSettings(settings: AppSettings): Promise<AppSettings> {
  return sendJson<AppSettings>('/api/masters/settings', 'PUT', settings)
}
export const useServersMaster = () => useMaster<Server, ServerInput>('/api/masters/servers')
export const useRoomsMaster = () => useMaster<Room, RoomInput>('/api/masters/rooms')

// ── グループのメンバーと招待（グループ管理者）───────────
export function fetchManagedGroups(): Promise<Group[]> {
  return getJson<Group[]>('/api/groups/managed')
}

export function fetchMembers(groupId: string): Promise<{ members: GroupMember[]; invitations: GroupInvitation[] }> {
  return getJson(`/api/groups/${encodeURIComponent(groupId)}/members`)
}

export function updateMember(groupId: string, userId: string, role: GroupRole): Promise<GroupMember> {
  return sendJson(`/api/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`, 'PUT', { role })
}

export function removeMember(groupId: string, userId: string): Promise<void> {
  return sendJson(`/api/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`, 'DELETE')
}

export function inviteMember(groupId: string, email: string, role: GroupRole): Promise<GroupInvitation> {
  return sendJson(`/api/groups/${encodeURIComponent(groupId)}/invitations`, 'POST', { email, role })
}

export interface GroupContents {
  rooms: number; devices: number; images: number; albums: number; members: number; invitations: number
  /** アカウントごと消える人（このグループにしか入っていない閲覧者） */
  users_deleted: number
}

export function fetchGroupContents(groupId: string): Promise<GroupContents> {
  return getJson(`/api/groups/${encodeURIComponent(groupId)}/contents`)
}

/** グループを中身ごと消す。確認のためにグループ名を送る */
export function deleteGroup(groupId: string, confirmName: string): Promise<{ ok: boolean; deleted: GroupContents; self_deleted: boolean }> {
  return sendJson(`/api/groups/${encodeURIComponent(groupId)}/delete`, 'POST', { confirm_name: confirmName })
}

export function cancelInvitation(groupId: string, invitationId: string): Promise<void> {
  return sendJson(`/api/groups/${encodeURIComponent(groupId)}/invitations/${encodeURIComponent(invitationId)}`, 'DELETE')
}

export const useDevicesMaster = () => useMaster<Device, DeviceInput>('/api/masters/devices')

/** 登録 QR に入れる、1 回限りの登録トークンを発行する。 */
export function issueEnrollment(deviceId: string): Promise<EnrollmentTicket> {
  return sendJson<EnrollmentTicket>(`/api/masters/devices/${deviceId}/enrollment`, 'POST')
}

/** 登録を外す。端末は QR で登録し直すまで認証できなくなる。 */
export function clearEnrollment(deviceId: string): Promise<Device> {
  return sendJson<Device>(`/api/masters/devices/${deviceId}/enrollment`, 'DELETE')
}

export function fetchAuditLogs(limit = 500): Promise<AuditLog[]> {
  return getJson<AuditLog[]>(`/api/audit-logs?limit=${limit}`)
}
