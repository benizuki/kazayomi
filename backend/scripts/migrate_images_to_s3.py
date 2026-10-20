"""ローカルのディスク（DATA_DIR）に置いていた画像とサムネイルを、rustfs（S3 互換）に移す。

キーはそのまま（images/YYYYMMDD/<id>.jpg、thumbs/<id>.jpg）なので、DB は変えない。
すでに rustfs にあるものは飛ばすので、何度実行してもよい。ローカルのファイルは消さない
（確認できてから手で消す）。

    cd backend && uv run python scripts/migrate_images_to_s3.py            # 実際に移す
    cd backend && uv run python scripts/migrate_images_to_s3.py --dry-run  # 数えるだけ
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import get_settings  # noqa: E402
from core.blobstore import S3BlobStore  # noqa: E402
from domain.images import CONTENT_TYPES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="数えるだけで、移さない")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.s3_endpoint_url:
        print("S3_ENDPOINT_URL が設定されていません。backend/.env に rustfs の設定を入れてください。", file=sys.stderr)
        return 1
    store = S3BlobStore(endpoint_url=settings.s3_endpoint_url, access_key=settings.s3_access_key,
                        secret_key=settings.s3_secret_key, bucket=settings.s3_bucket, region=settings.s3_region)
    if not args.dry_run:
        store.ensure_bucket()

    data_dir = settings.data_dir
    # DB に載っている画像のキーと、そのサムネイルだけを移す（どこからも参照されないファイルは移さない）
    with sqlite3.connect(data_dir / "kazayomi.db") as conn:
        rows = conn.execute("SELECT id, path FROM images").fetchall()

    copied = skipped = missing = 0
    for image_id, key in rows:
        for blob_key in (key, f"thumbs/{image_id}.jpg"):
            path = data_dir / blob_key
            if not path.is_file():
                # サムネイルが無いのは問題ない（表示したときに作り直す）
                if blob_key == key:
                    missing += 1
                    print(f"見つからない: {blob_key}")
                continue
            if not args.dry_run and store.exists(blob_key):
                skipped += 1
                continue
            if not args.dry_run:
                store.put(blob_key, path.read_bytes(), CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
            copied += 1

    action = "移す予定" if args.dry_run else "移した"
    print(f"画像 {len(rows)} 件: {action} {copied} 個 / すでにあった {skipped} 個 / ファイルが無い {missing} 件")
    print(f"バケット: {settings.s3_bucket}（{settings.s3_endpoint_url}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
