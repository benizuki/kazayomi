"""画像の置き場（rustfs / S3 互換）。moto の偽の S3 で、保存・読み出し・ZIP・削除を通しで確かめる。"""
from __future__ import annotations

import zipfile

import pytest
from moto import mock_aws

from core import blobstore
from core.blobstore import BlobNotFound, LocalBlobStore, S3BlobStore
from domain import albums, images
from tests.conftest import make_jpeg


@pytest.fixture
def s3_store():
    with mock_aws():
        store = S3BlobStore(endpoint_url=None, access_key="test", secret_key="test",  # type: ignore[arg-type]
                            bucket="kazayomi-test", region="us-east-1")
        store.ensure_bucket()
        store.ensure_bucket()  # 2 回目（バケットがある）でも落ちない
        blobstore.init_blobstore(store)
        yield store


def test_s3_put_get_stream_delete(s3_store):
    s3_store.put("images/20261017/a.jpg", b"hello", "image/jpeg")
    assert s3_store.exists("images/20261017/a.jpg")
    assert s3_store.get("images/20261017/a.jpg") == b"hello"
    chunks, size = s3_store.stream("images/20261017/a.jpg")
    assert b"".join(chunks) == b"hello" and size == 5
    s3_store.delete("images/20261017/a.jpg")
    assert not s3_store.exists("images/20261017/a.jpg")
    with pytest.raises(BlobNotFound):
        s3_store.get("images/20261017/a.jpg")
    with pytest.raises(BlobNotFound):
        s3_store.stream("images/20261017/a.jpg")


def test_images_round_trip_on_s3(s3_store):
    record = images.save_image(make_jpeg(320, 240), source="upload", group_id="default", tags=["OK"])
    key = images.image_key(record["id"])
    assert s3_store.exists(key) and s3_store.exists(f"thumbs/{record['id']}.jpg")

    chunks, size, content_type = images.open_image(record["id"])
    assert content_type == "image/jpeg" and size == record["size_bytes"]
    assert b"".join(chunks)[:2] == b"\xff\xd8"

    album = albums.create_album({"name": "A", "group_id": "default"})
    albums.add_items(album["id"], [record["id"]])
    _, buffer = albums.export_zip(album["id"])
    with zipfile.ZipFile(buffer) as zf:
        assert len(zf.namelist()) == 1

    assert images.delete_images([record["id"]]) == 1
    assert not s3_store.exists(key)
    assert not s3_store.exists(f"thumbs/{record['id']}.jpg")


def test_keys_cannot_escape(tmp_path):
    store = LocalBlobStore(tmp_path)
    for bad in ("../x", "/etc/passwd", "images/../../x", ""):
        with pytest.raises(ValueError):
            store.put(bad, b"x", "text/plain")
