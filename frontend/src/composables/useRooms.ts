import { ref } from 'vue'
import type { Room } from '@/types'
import { getJson, sendJson } from './http'

/** 自分が見られるグループのルーム（閲覧用）。編集はマスター（useMasters）で行う。 */
export function useRooms() {
  const rooms = ref<Room[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchRooms(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      rooms.value = await getJson<Room[]>('/api/rooms')
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  return { rooms, loading, error, fetchRooms }
}

/** Ayame に入るための入室チケット。接続のたびに取り直す（1 分・1 回限り）。 */
export async function issueRoomTicket(roomId: string): Promise<string> {
  const res = await sendJson<{ ticket: string }>(`/api/rooms/${roomId}/ticket`, 'POST')
  return res.ticket
}

export function getRoom(id: string): Promise<Room> {
  return getJson<Room>(`/api/rooms/${id}`)
}
