import type { ImageListResponse, ImageRecord, ImageSummaryRow, TagCount, TagMode } from '@/types'
import { downloadPost, getJson, sendJson } from './http'

/** ライブラリの API。状態は持たない（状態は呼び出す composable 側で持つ）。 */

export interface ImageQuery {
  roomId?: string | null
  /** roomId が 'none' のときだけ効く。撮像時点のルーム名（'' は手動の取り込み） */
  roomName?: string | null
  dateFrom?: string | null
  dateTo?:   string | null
  tags?:     string[]
  favorite?: boolean | null
  limit?:    number
  offset?:   number
}

export function listImages(query: ImageQuery): Promise<ImageListResponse> {
  const params = new URLSearchParams()
  if (query.roomId) params.set('room_id', query.roomId)
  if (query.roomId === 'none' && query.roomName != null) params.set('room_name', query.roomName)
  if (query.dateFrom) params.set('date_from', query.dateFrom)
  if (query.dateTo) params.set('date_to', query.dateTo)
  if (query.tags?.length) params.set('tags', query.tags.join(','))
  if (query.favorite != null) params.set('favorite', String(query.favorite))
  params.set('limit', String(query.limit ?? 500))
  params.set('offset', String(query.offset ?? 0))
  return getJson<ImageListResponse>(`/api/images?${params}`)
}

export function fetchSummary(dateFrom: string | null, dateTo: string | null): Promise<ImageSummaryRow[]> {
  const params = new URLSearchParams()
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  return getJson<ImageSummaryRow[]>(`/api/images/summary?${params}`)
}

export function fetchTags(): Promise<TagCount[]> {
  return getJson<TagCount[]>('/api/images/tags')
}

export function getImage(id: string): Promise<ImageRecord> {
  return getJson<ImageRecord>(`/api/images/${id}`)
}

export function updateImage(id: string, patch: Partial<Pick<ImageRecord, 'tags' | 'note' | 'favorite' | 'markers'>>): Promise<ImageRecord> {
  return sendJson<ImageRecord>(`/api/images/${id}`, 'PATCH', patch)
}

export function batchTags(ids: string[], tags: string[], mode: TagMode): Promise<{ updated: number }> {
  return sendJson('/api/images/tags/batch', 'POST', { ids, tags, mode })
}

export function deleteImages(ids: string[]): Promise<{ deleted: number }> {
  return sendJson('/api/images/delete', 'POST', { ids })
}

export function countAlbumUsage(ids: string[]): Promise<{ count: number }> {
  return sendJson('/api/images/album-usage', 'POST', { ids })
}

export function downloadZip(ids: string[]): Promise<void> {
  return downloadPost('/api/images/zip', { ids }, 'kazayomi-images.zip')
}

export const thumbUrl = (id: string): string => `/api/images/${id}/thumb`
export const fileUrl = (id: string): string => `/api/images/${id}/file`
export const downloadUrl = (id: string): string => `/api/images/${id}/file?download=true`
