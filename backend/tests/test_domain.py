"""domain 層のテスト。TestClient を使わず関数を直接呼ぶ。"""
from __future__ import annotations

import zipfile
from datetime import datetime, timedelta

import pytest

from core import kv
from core.blobstore import get_blobstore
from domain import albums, captures, rooms, images, servers
from domain.captures import CaptureAuthError
from domain.common import NotFoundError
from tests.conftest import make_room, make_group, make_jpeg, principal


def _save(group_id: str = "default", **kwargs) -> dict:
    return images.save_image(make_jpeg(), source=kwargs.pop("source", "upload"), group_id=group_id, **kwargs)


# ── ルーム・サーバ ────────────────────────────────


def test_room_requires_unique_room_id():
    make_room()
    with pytest.raises(ValueError, match="同じルームID"):
        rooms.create_room({"name": "別名", "ayame_room_id": "line-1", "group_id": "default"})


def test_room_rejects_invalid_room_id_and_unknown_group():
    with pytest.raises(ValueError, match="ルームID"):
        rooms.create_room({"name": "a", "ayame_room_id": "has space", "group_id": "default"})
    with pytest.raises(ValueError, match="グループが見つかりません"):
        rooms.create_room({"name": "a", "ayame_room_id": "a", "group_id": "nope"})


def test_room_signaling_url_comes_from_server_or_default():
    servers.create_server({"name": "既定", "signaling_url": "ws://default:3000/signaling", "is_default": True})
    server = servers.create_server({"name": "工場A", "signaling_url": "wss://ayame.example.com/signaling"})
    with_server = rooms.create_room({"name": "a", "ayame_room_id": "a", "group_id": "default", "server_id": server["id"]})
    without = make_room("b", "b")
    assert with_server["signaling_url"] == "wss://ayame.example.com/signaling"
    assert with_server["server_name"] == "工場A"
    assert without["signaling_url"] == "ws://default:3000/signaling"


def test_server_rejects_non_websocket_url_and_delete_in_use():
    with pytest.raises(ValueError, match="ws://"):
        servers.create_server({"name": "x", "signaling_url": "http://x"})
    server = servers.create_server({"name": "x", "signaling_url": "ws://x/signaling"})
    rooms.create_room({"name": "a", "ayame_room_id": "a", "group_id": "default", "server_id": server["id"]})
    with pytest.raises(ValueError, match="使うルーム"):
        servers.delete_server(server["id"])


def test_signaling_origins_include_servers():
    servers.create_server({"name": "b", "signaling_url": "wss://ayame.example.com:3443/signaling"})
    assert servers.signaling_origins() == ["wss://ayame.example.com:3443"]


def test_rooms_are_scoped_by_group():
    make_group("a")
    make_group("b")
    make_room("A", "room-a", "a")
    make_room("B", "room-b", "b")
    viewer = principal("user", {"a"})
    assert [c["name"] for c in rooms.list_rooms(viewer)] == ["A"]
    other = rooms.find_by_room("room-b")
    with pytest.raises(NotFoundError):
        rooms.get_room(other["id"], viewer)
    assert len(rooms.list_rooms(principal("admin"))) == 2


def test_deleting_room_keeps_images():
    room = make_room()
    record = _save(source="camera", room=room)
    rooms.delete_room(room["id"])
    kept = images.get_image(record["id"])
    assert kept["room_id"] is None
    assert kept["room_name"] == "ライン1"


# ── 画像 ────────────────────────────────────────────


def test_save_image_writes_file_and_thumbnail():
    record = images.save_image(make_jpeg(400, 300), source="upload", group_id="default", source_name="a.jpg", tags=["OK", "OK", " "])
    assert (record["width"], record["height"]) == (400, 300)
    assert record["tags"] == ["OK"]
    store = get_blobstore()
    key = images.image_key(record["id"])
    assert key.startswith(f"images/{record['date_key']}/") and key.endswith(".jpg")
    assert store.exists(key) and store.exists(f"thumbs/{record['id']}.jpg")
    assert images.read_thumbnail(record["id"])[:2] == b"\xff\xd8"  # JPEG


def test_missing_thumbnail_is_recreated():
    record = _save()
    get_blobstore().delete(f"thumbs/{record['id']}.jpg")
    assert images.read_thumbnail(record["id"])[:2] == b"\xff\xd8"
    assert get_blobstore().exists(f"thumbs/{record['id']}.jpg")


def test_save_image_rejects_non_image():
    with pytest.raises(ValueError, match="画像として読み込めません"):
        images.save_image(b"not an image", source="upload", group_id="default")


def test_list_filters_by_room_date_tag_and_favorite():
    room = make_room()
    today = datetime.now().astimezone()
    a = _save(source="camera", room=room, captured_at=today, tags=["NG"])
    b = _save(source="camera", room=room, captured_at=today - timedelta(days=3))
    c = _save(captured_at=today)
    images.update_image(b["id"], {"favorite": True})

    def ids(**kwargs):
        return {r["id"] for r in images.list_images(images.ImageFilter(**kwargs))["items"]}

    assert ids(room_id=room["id"]) == {a["id"], b["id"]}
    assert ids(room_id="none") == {c["id"]}
    assert ids(date_from=today.strftime("%Y%m%d")) == {a["id"], c["id"]}
    assert ids(tags=["NG"]) == {a["id"]}
    assert ids(favorite=True) == {b["id"]}


def test_images_are_scoped_by_group():
    make_group("a")
    make_group("b")
    mine = _save("a", tags=["x"])
    theirs = _save("b", tags=["y"])
    viewer = principal("power", {"a"})

    listed = images.list_images(images.ImageFilter(group_ids=viewer.visible_group_ids()))["items"]
    assert [r["id"] for r in listed] == [mine["id"]]
    assert [t["tag"] for t in images.tag_counts(viewer.visible_group_ids())] == ["x"]
    with pytest.raises(NotFoundError):
        images.get_image(theirs["id"], viewer)
    with pytest.raises(NotFoundError):
        images.read_thumbnail(theirs["id"], viewer)
    # 一括操作でも、見られない画像には触れない
    assert images.batch_update_tags([mine["id"], theirs["id"]], ["z"], "add", viewer) == 1
    assert images.delete_images([theirs["id"]], viewer) == 0
    assert images.get_image(theirs["id"])["tags"] == ["y"]


def test_filter_images_of_deleted_room_by_name():
    room = make_room()
    kept = _save(source="camera", room=room)
    rooms.delete_room(room["id"])
    upload = _save()
    by_name = images.list_images(images.ImageFilter(room_id="none", room_name="ライン1"))["items"]
    uploads = images.list_images(images.ImageFilter(room_id="none", room_name=""))["items"]
    assert [r["id"] for r in by_name] == [kept["id"]]
    assert [r["id"] for r in uploads] == [upload["id"]]


def test_list_paginates_newest_first():
    base = datetime.now().astimezone()
    saved = [_save(captured_at=base - timedelta(minutes=i)) for i in range(5)]
    page1 = images.list_images(images.ImageFilter(), limit=2)
    assert [r["id"] for r in page1["items"]] == [saved[0]["id"], saved[1]["id"]]
    assert page1["total"] == 5 and page1["next_offset"] == 2
    assert images.list_images(images.ImageFilter(), limit=2, offset=4)["next_offset"] is None


def test_summary_counts_by_room_and_date():
    room = make_room()
    _save(source="camera", room=room)
    _save(source="camera", room=room)
    _save()
    counts = {(r["room_id"], r["count"]) for r in images.summary()}
    assert (room["id"], 2) in counts and (None, 1) in counts


def test_batch_tags_add_replace_remove():
    a = _save(tags=["x"])
    b = _save()
    images.batch_update_tags([a["id"], b["id"]], ["y"], "add")
    assert images.get_image(a["id"])["tags"] == ["x", "y"]
    images.batch_update_tags([a["id"]], ["x"], "remove")
    assert images.get_image(a["id"])["tags"] == ["y"]
    images.batch_update_tags([a["id"], b["id"]], [], "replace")
    assert images.tag_counts() == []


def test_tags_ignore_width_and_case_differences():
    # 全角・半角、大文字・小文字、先頭の # は同じタグとみなし、最初の書き方を残す
    a = _save(tags=["NG", "ｎｇ", "#ng", "傷"])
    assert a["tags"] == ["NG", "傷"]
    b = _save(tags=["ng"])
    images.batch_update_tags([a["id"], b["id"]], ["Ｎｇ", "要確認"], "add")
    assert images.get_image(a["id"])["tags"] == ["NG", "傷", "要確認"]
    assert images.get_image(b["id"])["tags"] == ["ng", "要確認"]
    # 絞り込みも表記ゆれを問わない
    found = images.list_images(images.ImageFilter(tags=["nG"]))["items"]
    assert {r["id"] for r in found} == {a["id"], b["id"]}
    # 一覧ではまとめて数え、多く使われている書き方で返す
    counts = {t["tag"]: t["count"] for t in images.tag_counts()}
    assert counts["要確認"] == 2 and sum(v for k, v in counts.items() if k.lower() == "ng") == 2
    images.batch_update_tags([a["id"]], ["NG"], "remove")
    assert images.get_image(a["id"])["tags"] == ["傷", "要確認"]


def test_tag_limits():
    with pytest.raises(ValueError):
        _save(tags=[f"t{i}" for i in range(21)])
    with pytest.raises(ValueError):
        _save(tags=["x" * 51])
    record = _save(tags=[f"t{i}" for i in range(20)])
    with pytest.raises(ValueError):
        images.batch_update_tags([record["id"]], ["もう一つ"], "add")


def test_markers_are_validated_and_rounded():
    record = _save()
    assert record["markers"] == []
    updated = images.update_image(record["id"], {"markers": [
        {"type": "ellipse", "x": 0.5, "y": 0.25, "width": 0.123456789, "height": 0.2, "rotation": -30},
        {"type": "polygon", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
    ]})
    assert updated["markers"][0] == {"type": "ellipse", "x": 0.5, "y": 0.25, "width": 0.12346, "height": 0.2, "rotation": 330.0}
    assert updated["markers"][1]["points"][2] == {"x": 1.0, "y": 1.0}
    for bad in (
        "not a list",
        [{"type": "rect"}],
        [{"type": "polygon", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}],
        [{"type": "ellipse", "x": "0.5", "y": 0, "width": 1, "height": 1}],
        [{"type": "ellipse", "x": 5, "y": 0, "width": 1, "height": 1}],
    ):
        with pytest.raises(ValueError):
            images.update_image(record["id"], {"markers": bad})
    assert images.update_image(record["id"], {"markers": []})["markers"] == []


def test_callout_markers():
    record = _save()
    updated = images.update_image(record["id"], {"markers": [
        {"type": "callout", "x": 0.2, "y": 0.3, "bx": 0.5, "by": 0.1, "text": "  ここに傷\n要確認  "},
    ]})
    assert updated["markers"] == [{"type": "callout", "x": 0.2, "y": 0.3, "bx": 0.5, "by": 0.1, "text": "ここに傷\n要確認"}]
    for bad in (
        [{"type": "callout", "x": 0.2, "y": 0.3, "bx": 0.5, "by": 0.1, "text": "x" * 201}],
        [{"type": "callout", "x": 0.2, "y": 0.3, "bx": 0.5, "by": 0.1, "text": 3}],
        [{"type": "callout", "x": 0.2, "y": 0.3, "text": "x"}],
    ):
        with pytest.raises(ValueError):
            images.update_image(record["id"], {"markers": bad})


def test_delete_removes_files_and_album_membership():
    record = _save()
    album = albums.create_album({"name": "A", "group_id": "default"})
    albums.add_items(album["id"], [record["id"]])
    assert images.count_album_usage([record["id"]]) == 1
    key = images.image_key(record["id"])
    assert images.delete_images([record["id"]]) == 1
    assert not get_blobstore().exists(key)
    assert not get_blobstore().exists(f"thumbs/{record['id']}.jpg")
    assert albums.list_items(album["id"]) == []
    with pytest.raises(NotFoundError):
        images.get_image(record["id"])


# ── 撮像 ────────────────────────────────────────────


def test_capture_flow_accepts_once():
    make_group("line")
    room = make_room(group_id="line")
    viewer = principal("user", {"line"}, email="op@example.com")
    issued = captures.create_capture({"room_id": room["id"], "tags": ["朝"], "note": "点検"}, viewer=viewer, ttl_seconds=60)
    assert captures.capture_status(issued["capture_id"])["status"] == "pending"

    record = captures.accept_upload(issued["capture_id"], issued["token"], make_jpeg(),
                                    captured_at="2026-10-14T09:30:00+09:00", source_name="image.jpg")
    assert record["room_id"] == room["id"]
    assert record["group_id"] == "line"
    assert record["captured_by"] == "op@example.com"
    assert record["tags"] == ["朝"] and record["note"] == "点検"
    assert record["source"] == "camera"
    status = captures.capture_status(issued["capture_id"])
    assert status == {"capture_id": issued["capture_id"], "status": "done", "image_id": record["id"]}

    with pytest.raises(CaptureAuthError, match="期限"):
        captures.accept_upload(issued["capture_id"], issued["token"], make_jpeg(), captured_at=None, source_name="")


def test_capture_requires_visible_room():
    make_group("a")
    room = make_room(group_id="a")
    with pytest.raises(NotFoundError):
        captures.create_capture({"room_id": room["id"]}, viewer=principal("user", {"other"}), ttl_seconds=60)


def test_wrong_token_does_not_consume_capture():
    room = make_room()
    issued = captures.create_capture({"room_id": room["id"]}, viewer=principal(), ttl_seconds=60)
    with pytest.raises(CaptureAuthError, match="正しくありません"):
        captures.accept_upload(issued["capture_id"], "wrong", make_jpeg(), captured_at=None, source_name="")
    captures.accept_upload(issued["capture_id"], issued["token"], make_jpeg(), captured_at=None, source_name="")


def test_expired_capture_is_rejected():
    room = make_room()
    kv.set_store(kv.MemoryStore())
    issued = captures.create_capture({"room_id": room["id"]}, viewer=principal(), ttl_seconds=0)
    assert captures.capture_status(issued["capture_id"])["status"] == "expired"
    with pytest.raises(CaptureAuthError):
        captures.accept_upload(issued["capture_id"], issued["token"], make_jpeg(), captured_at=None, source_name="")


# ── アルバム ────────────────────────────────────────


def test_album_group_defaults_to_only_group_and_is_enforced():
    make_group("a")
    make_group("b")
    viewer = principal("power", {"a"})
    album = albums.create_album({"name": "A"}, viewer)
    assert album["group_id"] == "a"
    with pytest.raises(PermissionError):
        albums.create_album({"name": "B", "group_id": "b"}, viewer)
    with pytest.raises(ValueError, match="グループを選んで"):
        albums.create_album({"name": "C"}, principal("power", {"a", "b"}))


def test_album_only_accepts_images_of_its_group():
    make_group("a")
    make_group("b")
    album = albums.create_album({"name": "A", "group_id": "a"})
    mine = _save("a")
    theirs = _save("b")
    assert albums.add_items(album["id"], [mine["id"], theirs["id"]]) == {"added": 1, "skipped": 1}


def test_albums_are_scoped_by_group():
    make_group("a")
    make_group("b")
    albums.create_album({"name": "A", "group_id": "a"})
    other = albums.create_album({"name": "B", "group_id": "b"})
    viewer = principal("user", {"a"})
    assert [a["name"] for a in albums.list_albums(viewer)] == ["A"]
    with pytest.raises(NotFoundError):
        albums.export_zip(other["id"], viewer)


def test_add_items_skips_duplicates_and_unknown_images():
    album = albums.create_album({"name": "A", "group_id": "default"})
    record = _save()
    assert albums.add_items(album["id"], [record["id"], "missing"]) == {"added": 1, "skipped": 1}
    assert albums.add_items(album["id"], [record["id"]]) == {"added": 0, "skipped": 1}
    assert [i["image"]["id"] for i in albums.list_items(album["id"])] == [record["id"]]


def test_export_zip_puts_images_flat():
    album = albums.create_album({"name": "検査 v1", "group_id": "default"})
    recs = [_save(tags=["OK"]) for _ in range(3)]
    albums.add_items(album["id"], [r["id"] for r in recs])

    filename, buffer = albums.export_zip(album["id"])
    assert filename == "検査_v1.zip"
    with zipfile.ZipFile(buffer) as zf:
        names = zf.namelist()
    assert len(names) == 3 and all("/" not in name for name in names)


def test_album_counts():
    album = albums.create_album({"name": "A", "group_id": "default"})
    recs = [_save(tags=["OK"]) for _ in range(4)]
    albums.add_items(album["id"], [r["id"] for r in recs])
    got = albums.get_album(album["id"])
    assert got["item_count"] == 4 and got["cover_image_id"] in {r["id"] for r in recs}


def test_default_server_is_used_by_rooms_without_server():
    from domain import rooms, servers

    room = make_room()
    # 既定のサーバがなければ、つなぎ先がない
    assert rooms.get_room(room["id"])["signaling_url"] == ""
    assert rooms.default_signaling_url() == ""

    a = servers.create_server({"name": "A", "signaling_url": "wss://a.example/signaling", "is_default": True})
    b = servers.create_server({"name": "B", "signaling_url": "wss://b.example/signaling"})
    got = rooms.get_room(room["id"])
    assert got["signaling_url"] == "wss://a.example/signaling" and got["server_id"] is None and got["server_name"] == "A"

    # 既定は 1 つだけ。B を既定にすると A は外れる。名前などだけ変えても既定は保たれる
    servers.update_server(b["id"], {**b, "is_default": True})
    assert [s["name"] for s in servers.list_servers() if s["is_default"]] == ["B"]
    servers.update_server(b["id"], {"name": "B2", "signaling_url": b["signaling_url"]})
    assert servers.default_server()["name"] == "B2"
    assert rooms.default_signaling_url() == "wss://b.example/signaling"

    # ルームでサーバを選んでいれば、そちらが優先
    rooms.update_room(room["id"], {**room, "server_id": a["id"]})
    assert rooms.get_room(room["id"])["signaling_url"] == "wss://a.example/signaling"

    # 既定のサーバを消すと、つなぎ先がなくなる
    rooms.update_room(room["id"], {**room, "server_id": None})
    servers.delete_server(b["id"])
    assert rooms.get_room(room["id"])["signaling_url"] == ""
