"""画像ファイルの置き場。rustfs（S3 互換）か、ローカルのディスク。

キーはどちらでも同じ（`images/YYYYMMDD/<id>.jpg`、`thumbs/<id>.jpg`）。
S3_ENDPOINT_URL を設定すると rustfs を使い、未設定なら DATA_DIR の下に置く（テストと、手早く試すとき用）。

rustfs をブラウザから直接見せない（署名付き URL を渡さない）のは、ブラウザから rustfs に届かなくてよく、
閲覧のたびに kazayomi でログインとグループの権限を確かめられるため。
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

_CHUNK = 1024 * 1024


class BlobNotFound(LookupError):
    """キーに対応するファイルが無い。"""


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def stream(self, key: str) -> tuple[Iterator[bytes], int]:
        """中身を少しずつ返す（大きな画像をメモリに丸ごと載せないため）。2 つめは大きさ（バイト）。"""
        ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


def _check_key(key: str) -> str:
    # キーはサーバーが作るもの（画像 ID と日付）だけ。念のため、上の階層を指すものは受け付けない
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError(f"invalid blob key: {key!r}")
    return key


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / _check_key(key)

    def put(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise BlobNotFound(key)
        return path.read_bytes()

    def stream(self, key: str) -> tuple[Iterator[bytes], int]:
        path = self._path(key)
        if not path.is_file():
            raise BlobNotFound(key)

        def chunks() -> Iterator[bytes]:
            with path.open("rb") as f:
                while chunk := f.read(_CHUNK):
                    yield chunk

        return chunks(), path.stat().st_size

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3BlobStore:
    """rustfs（S3 互換）。path 形式・署名 v4 で使う。"""

    def __init__(self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str, region: str) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                # rustfs は新しいチェックサムの既定（CRC）に合わないことがあるので、必要なときだけにする
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def ensure_bucket(self) -> None:
        """バケットが無ければ作る。起動時に 1 回呼ぶ。"""
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchBucket", "NotFound"):
                raise
            try:
                self._client.create_bucket(Bucket=self.bucket)
            except ClientError as create_exc:
                # gunicorn の別の worker が同時に作った
                if create_exc.response.get("Error", {}).get("Code") not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise

    def _not_found(self, exc) -> bool:
        return str(exc.response.get("Error", {}).get("Code", "")) in ("404", "NoSuchKey", "NotFound")

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self.bucket, Key=_check_key(key), Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self.bucket, Key=_check_key(key))
        except ClientError as exc:
            if self._not_found(exc):
                raise BlobNotFound(key) from exc
            raise
        return response["Body"].read()

    def stream(self, key: str) -> tuple[Iterator[bytes], int]:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self.bucket, Key=_check_key(key))
        except ClientError as exc:
            if self._not_found(exc):
                raise BlobNotFound(key) from exc
            raise
        body = response["Body"]

        def chunks() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(_CHUNK)
            finally:
                body.close()

        return chunks(), int(response.get("ContentLength") or 0)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=_check_key(key))
            return True
        except ClientError as exc:
            if self._not_found(exc):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=_check_key(key))


_store: BlobStore | None = None


def init_blobstore(store: BlobStore) -> BlobStore:
    global _store
    _store = store
    return _store


def get_blobstore() -> BlobStore:
    if _store is None:
        raise RuntimeError("init_blobstore() has not been called")
    return _store
