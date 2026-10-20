/**
 * 文字をクリップボードにコピーする。できたら true。
 *
 * navigator.clipboard は https か localhost（安全なコンテキスト）でしか使えない。
 * 開発や社内で http://<IP> から開いた画面でもコピーできるよう、そのときは
 * 見えないテキスト欄を選んで document.execCommand('copy') でコピーする（古い方法だが、どこでも動く）。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 権限で断られたときも、下の方法を試す
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  // 画面には出さず、スクロールもさせない（iOS は font-size が小さいと拡大するので 16px にする）
  area.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;'
  // ダイアログの中から呼ぶと、ダイアログの外の要素にはフォーカスできないことがあるので、開いている要素の中に置く
  const host = (document.activeElement?.closest('[role="dialog"]') as HTMLElement | null) ?? document.body
  host.appendChild(area)
  area.focus()
  area.select()
  area.setSelectionRange(0, text.length)
  let copied = false
  try {
    copied = document.execCommand('copy')
  } catch {
    copied = false
  }
  area.remove()
  return copied
}
