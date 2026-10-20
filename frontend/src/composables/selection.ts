import { ref } from 'vue'
import type { ImageRecord } from '@/types'

/** 一覧の 1 マス。 */
export interface GridItem {
  id:      string
  image:   ImageRecord
}

/**
 * サムネイルの選択。
 * - クリック: その 1 枚だけを選ぶ
 * - Shift+クリック: 直前に選んだ位置からの範囲を足す（表示順）
 * - Ctrl / Cmd+クリック、チェックボックス: 1 枚ずつ足し引きする
 * 範囲選択の起点は、Shift を押さずに選んだ位置とチェックボックスで操作した位置。
 */
export function useSelection(items: () => GridItem[]) {
  const selected = ref<Set<string>>(new Set())
  let anchor: number | null = null

  function replace(next: Set<string>): void {
    selected.value = next
  }

  function click(index: number, event: MouseEvent): void {
    const list = items()
    const item = list[index]
    if (!item) return
    if (event.shiftKey && anchor != null) {
      const next = new Set(selected.value)
      const [from, to] = anchor < index ? [anchor, index] : [index, anchor]
      for (let i = from; i <= to; i++) if (list[i]) next.add(list[i].id)
      replace(next)
      return
    }
    if (event.metaKey || event.ctrlKey) {
      toggle(index)
      return
    }
    anchor = index
    replace(new Set([item.id]))
  }

  function toggle(index: number, event?: MouseEvent): void {
    if (event?.shiftKey && anchor != null) {
      click(index, event)
      return
    }
    const item = items()[index]
    if (!item) return
    const next = new Set(selected.value)
    if (next.has(item.id)) next.delete(item.id)
    else next.add(item.id)
    anchor = index
    replace(next)
  }

  function selectAll(): void {
    replace(new Set(items().map((i) => i.id)))
  }

  function clear(): void {
    anchor = null
    replace(new Set())
  }

  /** 一覧から消えたものを選択から外す（再読み込みや削除のあと）。 */
  function prune(): void {
    const ids = new Set(items().map((i) => i.id))
    const next = new Set([...selected.value].filter((id) => ids.has(id)))
    if (next.size !== selected.value.size) replace(next)
    anchor = null
  }

  return { selected, click, toggle, selectAll, clear, prune }
}
