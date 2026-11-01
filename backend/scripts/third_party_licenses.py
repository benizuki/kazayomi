"""入っている Python パッケージのライセンス文を集め、1 つのテキストファイルに書き出す。

コンテナのビルドで、依存関係を入れた直後に実行する（Dockerfile を参照）。
書き出したファイルは画面のメニューから開ける。

    cd backend && uv run python scripts/third_party_licenses.py ../frontend/dist/licenses/backend.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import Distribution, distributions
from pathlib import Path

LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|authors)([.\-_].*)?$", re.IGNORECASE)


def _license_name(dist: Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    # License に全文を入れているパッケージがあるので、1 行目だけ使う
    if meta.get("License") and meta["License"].strip():
        return meta["License"].strip().splitlines()[0]
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(classifiers) or "(記載なし)"


def _license_texts(dist: Distribution) -> list[str]:
    files = sorted(
        (f for f in dist.files or [] if LICENSE_FILE.match(f.name) and ".dist-info" in str(f)),
        key=str,
    )
    return [Path(f.locate()).read_text(encoding="utf-8", errors="replace").strip() for f in files]


def build(dists: list[Distribution]) -> str:
    rows = sorted({(d.metadata["Name"], d.version): d for d in dists}.items(), key=lambda kv: kv[0][0].lower())
    header = [
        "kazayomi のサーバ（Python）に含まれる第三者のソフトウェアと、そのライセンスです。",
        "",
        *(f"- {name}@{version} ({_license_name(d)})" for (name, version), d in rows),
    ]
    sections = []
    for (name, version), d in rows:
        homepage = d.metadata.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in d.metadata.get_all("Project-URL") or []), ""
        )
        texts = _license_texts(d)
        sections.append("\n".join([
            "=" * 72,
            f"{name}@{version}",
            f"License: {_license_name(d)}",
            *([f"Source: {homepage}"] if homepage else []),
            "-" * 72,
            "\n\n".join(texts) if texts else "パッケージにライセンス文が含まれていません。上の License の項目を参照してください。",
        ]))
    return "\n\n".join(["\n".join(header), *sections]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="書き出すファイル")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(list(distributions())), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
