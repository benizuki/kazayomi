/** 表示用の整形。 */

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function formatDateKey(key: string): string {
  return key.length === 8 ? `${key.slice(0, 4)}/${key.slice(4, 6)}/${key.slice(6)}` : key
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

/** Date → YYYYMMDD（ローカル日付）。 */
export function toDateKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`
}

/** input[type=date] の値（YYYY-MM-DD）と相互に変換する。 */
export function inputDateToKey(value: string): string {
  return value.replaceAll('-', '')
}
export function keyToInputDate(key: string): string {
  return key.length === 8 ? `${key.slice(0, 4)}-${key.slice(4, 6)}-${key.slice(6)}` : ''
}
