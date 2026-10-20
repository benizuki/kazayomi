// 容量の上限は、画面では MB で入れ、API にはバイトで送る（既定の 100MB をそのまま書けるように）
const MB = 1024 ** 2

/** MB → バイト。空なら無制限（null） */
export function toBytes(mb: string | number | null): number | null {
  if (mb === null || mb === '') return null
  const value = Number(mb)
  if (!Number.isFinite(value) || value <= 0) throw new Error('容量の上限は 0 より大きい数にしてください（無制限にするときは空にします）。')
  return Math.round(value * MB)
}

/** バイト → MB（入力欄に入れる文字列）。無制限は空 */
export function toMb(bytes: number | null): string {
  return bytes == null ? '' : String(Math.round(bytes / MB))
}
