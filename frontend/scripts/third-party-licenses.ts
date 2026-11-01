// ビルド成果物に入った npm パッケージのライセンス文を集め、dist/licenses/ に書き出す。
// minify でライセンスコメントが消えるので、配る JS・CSS・フォントの著作権表示はここで添える。
// 使っていない依存まで並べないよう、package.json ではなく実際にバンドルされたモジュールから数える。
import fs from 'node:fs'
import path from 'node:path'
import type { Plugin } from 'vite'

type Pkg = { name: string; version: string; license: string; homepage: string; text: string | null }

const LICENSE_FILE = /^(licen[cs]e|copying|notice)(\.|-|$)/i

// node_modules の中のパスから、パッケージのルートを求める（@scope/name にも対応）
function packageRoot(id: string): string | null {
  const file = id.replace(/^\0/, '').split('?')[0]
  const marker = `${path.sep}node_modules${path.sep}`
  const at = file.lastIndexOf(marker)
  if (at < 0) return null
  const rest = file.slice(at + marker.length).split(path.sep)
  const depth = rest[0].startsWith('@') ? 2 : 1
  return file.slice(0, at + marker.length) + rest.slice(0, depth).join(path.sep)
}

function readPkg(root: string): Pkg {
  const json = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'))
  const files = fs.readdirSync(root).filter((f) => LICENSE_FILE.test(f)).sort()
  const text = files.length
    ? files.map((f) => fs.readFileSync(path.join(root, f), 'utf8').trim()).join('\n\n')
    : null
  const repo = typeof json.repository === 'string' ? json.repository : json.repository?.url
  return {
    name:     json.name,
    version:  json.version,
    license:  typeof json.license === 'string' ? json.license : json.license?.type ?? '(記載なし)',
    homepage: json.homepage ?? repo ?? '',
    text,
  }
}

export function thirdPartyLicenses(options: { projectLicense: string }): Plugin {
  return {
    name: 'kazayomi-third-party-licenses',
    apply: 'build',
    generateBundle(_, bundle) {
      const roots = new Set<string>()
      for (const item of Object.values(bundle)) {
        const ids = item.type === 'chunk' ? item.moduleIds : item.originalFileNames
        for (const id of ids) {
          const root = packageRoot(path.resolve(id))
          if (root) roots.add(root)
        }
      }
      const pkgs = [...roots].map(readPkg)
        // 同じパッケージが複数の場所に入っていても 1 つにまとめる
        .filter((p, i, all) => all.findIndex((q) => q.name === p.name && q.version === p.version) === i)
        .sort((a, b) => a.name.localeCompare(b.name))

      const header = [
        'kazayomi の画面（ブラウザで動く JavaScript・CSS・フォント）に含まれる第三者のソフトウェアと、そのライセンスです。',
        '',
        ...pkgs.map((p) => `- ${p.name}@${p.version} (${p.license})`),
      ].join('\n')
      const sections = pkgs.map((p) => [
        '='.repeat(72),
        `${p.name}@${p.version}`,
        `License: ${p.license}`,
        ...(p.homepage ? [`Source: ${p.homepage}`] : []),
        '-'.repeat(72),
        p.text ?? 'パッケージにライセンス文が含まれていません。上の License の項目を参照してください。',
      ].join('\n'))

      this.emitFile({ type: 'asset', fileName: 'licenses/frontend.txt', source: [header, ...sections].join('\n\n') + '\n' })
      // kazayomi 自身のライセンス。見つからなければビルドを止める（黙って抜けると気付けない）
      this.emitFile({ type: 'asset', fileName: 'licenses/LICENSE.txt', source: fs.readFileSync(options.projectLicense, 'utf8') })
    },
  }
}
