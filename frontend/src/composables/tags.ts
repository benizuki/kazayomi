/**
 * タグの表記ゆれの扱い（バックエンドの domain/common.py と同じ決まり）。
 * 全角・半角と大文字・小文字の違いを同じタグとみなし、先頭の「#」は外す。
 */

export const MAX_TAGS = 20
export const MAX_TAG_LENGTH = 50

/** 比べるための形 */
export function tagKey(tag: string): string {
  return tag.normalize('NFKC').trim().replace(/^#+/, '').trim().toLocaleLowerCase()
}

/** 入力欄の「a, b, #c」を、タグの並びにする（空と重複は除く） */
export function splitTags(input: string): string[] {
  return uniqueTags(input.split(/[,、]/))
}

/** 表記ゆれの重複を除く。最初の書き方を残す */
export function uniqueTags(tags: string[]): string[] {
  const byKey = new Map<string, string>()
  for (const raw of tags) {
    const tag = raw.normalize('NFKC').trim().replace(/^#+/, '').trim()
    const key = tagKey(tag)
    if (key && !byKey.has(key)) byKey.set(key, tag)
  }
  return [...byKey.values()]
}
