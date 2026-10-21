import { computed, ref, watch } from 'vue'
import type { AyameConnection } from './useAyameConnection'

// 見やすい色から 1 つ選ぶ（タブごとに決める）。Kazami の画面にも同じ色で出る
const PALETTE = ['#ea4335', '#34a853', '#4285f4', '#fbbc04', '#ef20ef', '#00c8c8', '#ff8a00']

/**
 * レーザーポインター。オンの間は映像の上をドラッグした位置を Kazami に送り、Kazami の画面に重ねて出す。
 * 「ここを見て」と、現場の人に指し示すためのもの。オンの間は、ダブルクリックでのフォーカスは止める。
 */
export function usePointer(connection: AyameConnection) {
  const on = ref(false)
  const color = PALETTE[Math.floor(Math.random() * PALETTE.length)]

  /** つながっていて、ポインターに対応した Kazami のときだけ使える */
  const available = computed(() =>
    connection.status.value === 'connected' && connection.controlOpen.value
    && (connection.peerInfo.value?.capabilities?.includes('pointer') ?? false))

  // 切れたら、オンのまま残さない
  watch(available, (ok) => { if (!ok) on.value = false })

  function toggle(): void {
    on.value = available.value && !on.value
  }

  function send(point: { x: number, y: number }): void {
    if (!on.value) return
    connection.sendControl({ type: 'pointer', x: point.x, y: point.y, color })
  }

  return {
    on,
    available,
    /** VideoPlayer に渡す色。オフなら null（ポインターを使わない） */
    playerColor: computed(() => (on.value ? color : null)),
    toggle,
    send,
  }
}
