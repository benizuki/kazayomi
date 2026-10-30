"""SQLite の接続とスキーマ。

JSON ファイルではなく SQLite にしているのは、画像が数万枚になり、
日付・カメラ・タグでの絞り込みとアルバムとの関連を扱うため。
WAL にして、読み込み中の書き込みでロック待ちにならないようにしている。
"""
from __future__ import annotations

import fcntl
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    room_id       TEXT NOT NULL UNIQUE,
    signaling_url TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
    id           TEXT PRIMARY KEY,
    camera_id    TEXT,
    camera_name  TEXT NOT NULL DEFAULT '',
    captured_at  TEXT NOT NULL,
    date_key     TEXT NOT NULL,
    source       TEXT NOT NULL,
    source_name  TEXT NOT NULL DEFAULT '',
    path         TEXT NOT NULL,
    width        INTEGER NOT NULL,
    height       INTEGER NOT NULL,
    size_bytes   INTEGER NOT NULL,
    tags         TEXT NOT NULL DEFAULT '[]',
    note         TEXT NOT NULL DEFAULT '',
    favorite     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_captured ON images (captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_images_camera_date ON images (camera_id, date_key);

CREATE TABLE IF NOT EXISTS image_tags (
    image_id TEXT NOT NULL REFERENCES images (id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (image_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags (tag);

CREATE TABLE IF NOT EXISTS albums (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS album_items (
    album_id TEXT NOT NULL REFERENCES albums (id) ON DELETE CASCADE,
    image_id TEXT NOT NULL REFERENCES images (id) ON DELETE CASCADE,
    label    TEXT NOT NULL DEFAULT '',
    subset   TEXT NOT NULL DEFAULT 'none',
    added_at TEXT NOT NULL,
    PRIMARY KEY (album_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_album_items_image ON album_items (image_id);
"""

# スキーマの版。PRAGMA user_version に記録し、起動時に足りない分だけ順に当てる。
# 一度当てた移行は書き換えないこと（既に当たった DB には二度と流れない）。
# 変更が要るときは、新しい版を末尾に足す。
_MIGRATIONS: list[str] = [
    # v2: マスター（ユーザー・グループ・サーバ・チャネル）とグループでの絞り込み。
    # 「カメラ」を「チャネル」に改め、画像とアルバムに所属グループを持たせる。
    # 既存のデータは既定のグループ（default）に入れる。
    """
    CREATE TABLE IF NOT EXISTS groups (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    INSERT OR IGNORE INTO groups (id, name, created_at, updated_at)
        VALUES ('default', '既定のグループ', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

    CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT NOT NULL UNIQUE,
        name          TEXT NOT NULL DEFAULT '',
        role          TEXT NOT NULL,
        enabled       INTEGER NOT NULL DEFAULT 1,
        last_login_at TEXT,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_groups (
        user_id  TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        group_id TEXT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
        PRIMARY KEY (user_id, group_id)
    );

    CREATE TABLE IF NOT EXISTS servers (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
        signaling_url TEXT NOT NULL,
        note          TEXT NOT NULL DEFAULT '',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    );
    -- カメラごとに書いていたシグナリング URL は、サーバとして登録し直す
    INSERT OR IGNORE INTO servers (id, name, signaling_url, note, created_at, updated_at)
        SELECT lower(hex(randomblob(16))), signaling_url, signaling_url, '移行時に作成', created_at, created_at
        FROM (SELECT DISTINCT signaling_url, MIN(created_at) AS created_at FROM cameras WHERE signaling_url != '' GROUP BY signaling_url);

    ALTER TABLE cameras RENAME TO channels;
    ALTER TABLE channels ADD COLUMN group_id TEXT NOT NULL DEFAULT 'default' REFERENCES groups (id);
    ALTER TABLE channels ADD COLUMN server_id TEXT REFERENCES servers (id) ON DELETE SET NULL;
    UPDATE channels SET server_id = (SELECT s.id FROM servers s WHERE s.signaling_url = channels.signaling_url)
        WHERE signaling_url != '';
    ALTER TABLE channels DROP COLUMN signaling_url;
    CREATE INDEX IF NOT EXISTS idx_channels_group ON channels (group_id);

    DROP INDEX IF EXISTS idx_images_camera_date;
    ALTER TABLE images RENAME COLUMN camera_id TO channel_id;
    ALTER TABLE images RENAME COLUMN camera_name TO channel_name;
    ALTER TABLE images ADD COLUMN group_id TEXT NOT NULL DEFAULT 'default';
    ALTER TABLE images ADD COLUMN captured_by TEXT NOT NULL DEFAULT '';
    CREATE INDEX IF NOT EXISTS idx_images_channel_date ON images (channel_id, date_key);
    CREATE INDEX IF NOT EXISTS idx_images_group_captured ON images (group_id, captured_at DESC);

    ALTER TABLE albums ADD COLUMN group_id TEXT NOT NULL DEFAULT 'default';
    """,
    # v3: デバイス（Kazami 端末）。QR で登録した公開鍵で、端末を確かめる。
    # device_id は端末が名乗る ID（identifierForVendor）。登録するまでは空。
    """
    CREATE TABLE IF NOT EXISTS devices (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
        channel_id    TEXT REFERENCES channels (id) ON DELETE SET NULL,
        device_id     TEXT,
        public_key    TEXT,
        enrolled_at   TEXT,
        last_seen_at  TEXT,
        last_ip       TEXT NOT NULL DEFAULT '',
        note          TEXT NOT NULL DEFAULT '',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_device_id ON devices (device_id) WHERE device_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_devices_channel ON devices (channel_id);
    """,
    # v4: Ayame にならって「チャネル」を「ルーム」に改める。
    # Ayame の roomId は ayame_room_id、ルームの行を指す列は room_id にする（同じ名前にならないように）。
    # 表の名前を変えると、ほかの表の外部キーの参照先も SQLite が書き換える。
    """
    DROP INDEX IF EXISTS idx_channels_group;
    DROP INDEX IF EXISTS idx_images_channel_date;
    DROP INDEX IF EXISTS idx_devices_channel;

    ALTER TABLE channels RENAME TO rooms;
    ALTER TABLE rooms RENAME COLUMN room_id TO ayame_room_id;
    CREATE INDEX IF NOT EXISTS idx_rooms_group ON rooms (group_id);

    ALTER TABLE images RENAME COLUMN channel_id TO room_id;
    ALTER TABLE images RENAME COLUMN channel_name TO room_name;
    CREATE INDEX IF NOT EXISTS idx_images_room_date ON images (room_id, date_key);

    ALTER TABLE devices RENAME COLUMN channel_id TO room_id;
    CREATE INDEX IF NOT EXISTS idx_devices_room ON devices (room_id);
    """,
    # v5: タグは表記ゆれ（全角・半角、大文字・小文字）を同じものとして扱う。
    # 比べるための形（tag_key）を持たせる。NFKC は SQL では作れないので、値は _fill_tag_keys が入れる。
    # あわせて、画像に描いた図形（楕円・多角形。画像の幅・高さに対する割合）を持たせる。
    """
    ALTER TABLE image_tags ADD COLUMN tag_key TEXT;
    CREATE INDEX IF NOT EXISTS idx_image_tags_key ON image_tags (tag_key, image_id);
    ALTER TABLE images ADD COLUMN markers TEXT NOT NULL DEFAULT '[]';
    """,
    # v6: アルバムのラベルをやめ、画像のタグで分ける。アルバムには「分類に使うタグ」（class_tags）を持たせ、
    # 画像のタグのうちそのどれを持つかで、ZIP のフォルダと train / val の振り分けを決める。
    # 今あるラベルを画像のタグと class_tags に移し、ラベルの列を消すのは _move_album_labels が行う（NFKC が要るため）。
    """
    ALTER TABLE albums ADD COLUMN class_tags TEXT NOT NULL DEFAULT '[]';
    """,
    # v7: train / val の分割をやめる（アルバムはタグで分けて、そのまま ZIP にする）
    """
    ALTER TABLE album_items DROP COLUMN subset;
    """,
    # v8: アルバムの「分類に使うタグ」をやめる（アルバムでも、ライブラリと同じくタグで絞り込む）
    """
    ALTER TABLE albums DROP COLUMN class_tags;
    """,
    # v9: グループごとの役割と招待。
    # - user_groups.role: そのグループでの役割（owner＝グループ管理者 / editor / viewer）。
    #   全体のロール（users.role）とあわせて、強いほうが効く。今いる人は viewer にする（全体のロールで今までどおり動く）
    # - groups.created_by: 自分で作ったグループの数を数える（当時は誰でも作れた。いまはアプリの管理者だけが作るので使わない）
    # - group_invitations: グループ管理者がメールアドレスを指定して招待する。本人がそのアドレスでサインインすると参加できる
    """
    ALTER TABLE groups ADD COLUMN created_by TEXT NOT NULL DEFAULT '';
    ALTER TABLE user_groups ADD COLUMN role TEXT NOT NULL DEFAULT 'viewer';
    CREATE TABLE IF NOT EXISTS group_invitations (
        id         TEXT PRIMARY KEY,
        group_id   TEXT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
        email      TEXT NOT NULL,
        role       TEXT NOT NULL,
        invited_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        UNIQUE (group_id, email)
    );
    CREATE INDEX IF NOT EXISTS idx_group_invitations_email ON group_invitations (email);
    CREATE INDEX IF NOT EXISTS idx_groups_created_by ON groups (created_by);
    """,
    # v10: 既定のサーバ。サーバを選んでいないルームが使う（1 つだけ。なければ環境変数の URL）
    """
    ALTER TABLE servers ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_servers_default ON servers (is_default) WHERE is_default = 1;
    """,
    # v11: 環境変数のシグナリング URL をやめたので、サーバが 1 つだけなら既定にしておく（つなげなくならないように）。
    # グループごとの容量の上限（quota_bytes、NULL は無制限）と、使用量に数えるサムネイルの大きさ（thumb_bytes）。
    # app_settings はアプリ全体の設定（新しく作られるグループの容量など）
    """
    UPDATE servers SET is_default = 1
        WHERE (SELECT COUNT(*) FROM servers) = 1 AND NOT EXISTS (SELECT 1 FROM servers WHERE is_default = 1);
    ALTER TABLE groups ADD COLUMN quota_bytes INTEGER;
    ALTER TABLE images ADD COLUMN thumb_bytes INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE IF NOT EXISTS app_settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # v12: サーバの種類。cloudflare は、シグナリングは Ayame のまま、TURN の認証情報を Cloudflare から発行して渡す
    """
    ALTER TABLE servers ADD COLUMN kind TEXT NOT NULL DEFAULT 'ayame';
    ALTER TABLE servers ADD COLUMN turn_key_id TEXT NOT NULL DEFAULT '';
    ALTER TABLE servers ADD COLUMN turn_api_token TEXT NOT NULL DEFAULT '';
    """,
]

_lock = threading.Lock()
_db_path: Path | None = None


def init_db(path: Path) -> None:
    """起動時に 1 回呼ぶ。テストでは一時ディレクトリを渡して差し替える。

    gunicorn の worker が同時に起動すると、WAL への切り替えとテーブル作成がぶつかって
    "database is locked" で起動に失敗する。ファイルロックで 1 プロセスずつ行う。
    """
    global _db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path.with_suffix(".init.lock"), "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            _db_path = path
            conn = _open(path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                _migrate(conn)
                _fill_tag_keys(conn)
                _move_album_labels(conn)
            finally:
                conn.close()
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _migrate(conn: sqlite3.Connection) -> None:
    """足りない版の移行を順に当てる。1 つの版は 1 トランザクションで当てる。"""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    if version == 0:
        # 新しい DB と、版を記録する前に作った DB（v1 相当）。どちらも IF NOT EXISTS で v1 にそろう
        conn.executescript(_SCHEMA)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        version = 1
    for index in range(version - 1, len(_MIGRATIONS)):
        target = index + 2  # _SCHEMA が v1、_MIGRATIONS[0] が v2
        # ALTER TABLE ... RENAME の途中で外部キーの検査に引っかからないよう、移行中だけ切る
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.executescript(f"BEGIN;\n{_MIGRATIONS[index]}\nPRAGMA user_version = {target};\nCOMMIT;")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")


def _fill_tag_keys(conn: sqlite3.Connection) -> None:
    """v5 より前に付けたタグに、比べるための形（tag_key）を入れる。入っていない行だけなので、2 回目からは何もしない。"""
    from domain.common import tag_key

    rows = conn.execute("SELECT rowid, tag FROM image_tags WHERE tag_key IS NULL").fetchall()
    if not rows:
        return
    conn.executemany("UPDATE image_tags SET tag_key = ? WHERE rowid = ?", [(tag_key(r["tag"]), r["rowid"]) for r in rows])
    conn.commit()


def _move_album_labels(conn: sqlite3.Connection) -> None:
    """アルバムのラベル（v5 まで）を、画像のタグとアルバムの class_tags に移してから、ラベルの列を消す。

    ラベルの列が無くなっていれば何もしない（2 回目からと、移したあと）。
    1 枚に付けられるタグの上限を超える画像には、ラベルをタグとして足さない。
    class_tags は v8 で消すので、列が無ければ（v8 まで一度に上げたとき）画像のタグに移すだけにする。
    """
    import json

    from domain.common import MAX_TAG_LENGTH, MAX_TAGS, normalize_tags, tag_key

    columns = {row[1] for row in conn.execute("PRAGMA table_info(album_items)")}
    if "label" not in columns:
        return
    conn.execute("BEGIN")
    try:
        class_tags: dict[str, list[str]] = {}
        rows = conn.execute("SELECT album_id, image_id, label FROM album_items WHERE label != ''").fetchall()
        for row in rows:
            try:
                normalized = normalize_tags([row["label"][:MAX_TAG_LENGTH]])
            except ValueError:
                continue
            if not normalized:
                continue
            label = normalized[0]
            key = tag_key(label)
            album_tags = class_tags.setdefault(row["album_id"], [])
            if key not in {tag_key(t) for t in album_tags}:
                album_tags.append(label)
            image = conn.execute("SELECT tags FROM images WHERE id = ?", (row["image_id"],)).fetchone()
            if image is None:
                continue
            tags: list[str] = json.loads(image["tags"])
            if key in {tag_key(t) for t in tags} or len(tags) >= MAX_TAGS:
                continue
            tags.append(label)
            conn.execute("UPDATE images SET tags = ? WHERE id = ?", (json.dumps(tags, ensure_ascii=False), row["image_id"]))
            conn.execute(
                "INSERT OR IGNORE INTO image_tags (image_id, tag, tag_key) VALUES (?, ?, ?)",
                (row["image_id"], label, key),
            )
        album_columns = {row[1] for row in conn.execute("PRAGMA table_info(albums)")}
        if "class_tags" in album_columns:
            for album_id, tags in class_tags.items():
                conn.execute("UPDATE albums SET class_tags = ? WHERE id = ?",
                             (json.dumps(tags[:MAX_TAGS], ensure_ascii=False), album_id))
        conn.execute("ALTER TABLE album_items DROP COLUMN label")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def schema_version() -> int:
    with connect() as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return version


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    # 外部キーは接続ごとに有効化しないと効かない（画像を消したときのアルバムからの除去に必要）
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """1 つの処理を 1 トランザクションで行う。例外ならロールバックする。"""
    if _db_path is None:
        raise RuntimeError("init_db() has not been called")
    conn = _open(_db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
