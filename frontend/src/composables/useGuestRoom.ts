import { ref } from 'vue'
import type { GuestEnrollment, GuestRoom } from '@/types'
import { getJson, sendJson } from './http'

/** ゲストの、自分の一時的なルーム（1 人 1 ルーム）。開くとなければ作られ、期限が延びる。 */
export function useGuestRoom() {
  const room = ref<GuestRoom | null>(null)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    error.value = null
    try {
      room.value = await getJson<GuestRoom>('/api/guest/room')
    } catch (e) {
      error.value = (e as Error).message
    }
  }

  async function end(): Promise<void> {
    await sendJson('/api/guest/room', 'DELETE')
    room.value = null
  }

  return { room, error, load, end }
}

export function issueGuestEnrollment(): Promise<GuestEnrollment> {
  return sendJson<GuestEnrollment>('/api/guest/room/enrollment', 'POST')
}

export async function issueGuestTicket(): Promise<string> {
  return (await sendJson<{ ticket: string }>('/api/guest/room/ticket', 'POST')).ticket
}

export function guestSignalingUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/api/guest/room/signaling`
}

export function acceptTerms(version: string): Promise<{ ok: boolean }> {
  return sendJson('/api/guest/consent', 'POST', { version })
}
