import { ref } from 'vue'
import type { Album, AlbumItem } from '@/types'
import { getJson, sendJson } from './http'

/** アルバムの一覧。ライブラリの右パネルとアルバム一覧で使う。 */
export function useAlbums() {
  const albums = ref<Album[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAlbums(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      albums.value = await getJson<Album[]>('/api/albums')
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function createAlbum(name: string, description = '', groupId = ''): Promise<Album> {
    const album = await sendJson<Album>('/api/albums', 'POST', { name, description, group_id: groupId })
    await fetchAlbums()
    return album
  }

  return { albums, loading, error, fetchAlbums, createAlbum }
}

// ── 1 つのアルバムへの操作 ─────────────────────────

export function getAlbum(id: string): Promise<Album> {
  return getJson<Album>(`/api/albums/${id}`)
}

export function updateAlbum(id: string, patch: Partial<Pick<Album, 'name' | 'description'>>): Promise<Album> {
  return sendJson<Album>(`/api/albums/${id}`, 'PATCH', patch)
}

export function deleteAlbum(id: string): Promise<void> {
  return sendJson(`/api/albums/${id}`, 'DELETE')
}

export function listAlbumItems(id: string): Promise<AlbumItem[]> {
  return getJson<AlbumItem[]>(`/api/albums/${id}/items`)
}

export function addAlbumItems(id: string, ids: string[]): Promise<{ added: number; skipped: number }> {
  return sendJson(`/api/albums/${id}/items`, 'POST', { ids })
}

export function removeAlbumItems(id: string, ids: string[]): Promise<{ removed: number }> {
  return sendJson(`/api/albums/${id}/items/remove`, 'POST', { ids })
}

export const albumExportUrl = (id: string): string => `/api/albums/${id}/export`
