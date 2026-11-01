# kazayomi（風読み）

## 関連

- Kazami（iPhone / iPad のカメラアプリ。Ayame で映像を送る）。別のリポジトリ

## 目的

現場に置いた Kazami（iPhone / iPad）の映像をブラウザで確認し、音声でやり取りし、撮像した静止画を蓄積して、気に入った画像をアルバム（学習用データセット）にまとめる。

自分のサーバ（手元の PC や社内のサーバ）で docker compose で動かすセルフホスト版。ゲストなど、外の人に開く機能は持たない。

名前は「風読み」から。風見（Kazami）が示すものを読み取る側、という意味。

## システム構成

```
[Kazami (iPhone)] ──Ayame P2P（映像・音声・DataChannel）── [ブラウザ: kazayomi の画面]
        │                                                          │
        └──── 静止画を HTTP でアップロード ────▶ [kazayomi]  FastAPI ＋ Vue の配信、SQLite
                                                  [Ayame]     シグナリング（kazayomi と同じネットワーク名前空間）
                                                  [Valkey]    トークン類
                                                  [rustfs]    画像・サムネイル（S3 互換）
```

- docker compose の 1 つの構成で動かす。公開するポートは kazayomi の 8080 と Ayame の 3000。Ayame と kazayomi は、名前空間とポートだけを持つ `net` コンテナに同居する

- Vue 3 / Vuetify / TypeScript / Vite ＋ FastAPI（uv で依存を管理）
- 画像は rustfs（S3 互換、`rustfs/rustfs:1.0.4`）に、キー `images/YYYYMMDD/<id>.jpg`、サムネイルは `thumbs/<id>.jpg` で置く
  - ブラウザには rustfs を直接見せず、kazayomi が読んで返す（閲覧のたびにログインとグループの権限を確かめるため。ブラウザから rustfs に届かなくてよい）
  - `S3_ENDPOINT_URL` が未設定なら、同じキーで `DATA_DIR` の下に置く（テストと、手早く試すとき用）
  - ローカルのディスクから移すときは `backend/scripts/migrate_images_to_s3.py`
- メタデータは `data/kazayomi.db`（SQLite、WAL）
  - 雛形の既定は JSON ファイルだが、画像が数千枚になり、日付・カメラ・タグでの絞り込みとアルバムとの関連があるため SQLite にした
- 撮像トークンは Valkey（Redis 互換の OSS）に TTL 付きで置く。期限切れの掃除を任せられるのと、gunicorn の worker を複数にしても共有できるため
  - `VALKEY_URL` が未設定なら、プロセス内のメモリで代用する（worker 1 つの開発時とテスト向け）

### Ayame の制約

- 1 ルーム＝カメラ 1 台＋視聴者 1 人。同じルームを単一ビューとマルチビューで同時には開けない。3 人目は Ayame に拒否される（reason=full）ので「他の画面がこのルームを見ています」と出す
- マルチビューはルームの数だけ P2P 接続を張る。目安は 720p で 9 台
- 後から register した側が offer を出す（Ayame の仕様）。ブラウザはどちらの役も受け持つ
- 受信側のコーデック優先順位は `setCodecPreferences` で決める

## エンティティ

### ユーザー (user)

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| メールアドレス | email | text | ✓ | ✓ | ✓ | 一意。Google のログインID。小文字にそろえる |
| 表示名 | name | text |  | ✓ | ✓ | 空なら最初のログインで Google の名前を入れる |
| ロール | role | enum(admin,device_admin,power,user) | ✓ | ✓ |  | 既定=user |
| 所属グループ | group_ids | ref(group)[] |  | ✓ |  | admin は全グループを見るので使わない |
| 有効 | enabled | bool | ✓ | ✓ |  | 既定=true。外すと次のリクエストから入れない |
| 最終ログイン | last_login_at | datetime |  | ✓ |  | |

### グループ (group)

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| グループID | id | text | ✓ | ✓ |  | 一意。半角英数字と _ -。変えられない（画像・アルバムが参照する） |
| グループ名 | name | text | ✓ | ✓ | ✓ | 一意 |
| 容量の上限 | quota_bytes | int |  | ✓ |  | 画像とサムネイルの合計（バイト）。空は無制限。アプリの管理者だけが変えられる |

**容量**: 使用量は、グループの画像とサムネイルの大きさの合計（`images.size_bytes + thumb_bytes`。v11 より前のサムネイルは 0 として数える）。
rustfs のバケットは全グループで 1 つなので、rustfs の機能ではなく kazayomi が保存のときに確かめ、上限を超えるなら 507 と理由を返す（Kazami の撮像ボタン・画面からの撮像のどちらも）。
新しく作るグループには、マスター › 設定 の「新しいグループの容量」（`app_settings`）を付ける。決めていないときは 100MB。「無制限」にもできる。
使用量はマスター › グループ（アプリの管理者）と、マスター › メンバー（グループ管理者）に出す。

移行時に既定のグループ（`default`）を作り、それまでのルーム・画像・アルバムを入れた。

### サーバ (server)

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| サーバ名 | name | text | ✓ | ✓ | ✓ | 一意 |
| シグナリングURL | signaling_url | text | ✓ | ✓ |  | ws:// か wss://。kazayomi と Kazami の両方から届く URL（ブラウザは kazayomi 経由） |
| 種類 | kind | enum(ayame,cloudflare) | ✓ | ✓ |  | 既定=ayame。cloudflare はシグナリングは Ayame のまま、TURN の認証情報を Cloudflare（外部のサービス）で発行して渡す。社外のネットワーク同士など、P2P で届かない相手とつなぐときだけ使う |
| TURN キー ID | turn_key_id | text |  | ✓ |  | kind=cloudflare のとき必須。Cloudflare の Realtime → TURN のキー |
| API トークン | turn_api_token | text |  |  |  | kind=cloudflare のとき必須。API では返さない（`turn_api_token_set` だけ）。空で保存すると今の値のまま。監査ログにも残さない |
| メモ | note | longtext |  |  |  | |
| 既定 | is_default | bool |  | ✓ |  | 既定のサーバ。1 つだけ。サーバを選んでいないルームと、ルームを割り当てていない端末が使う |

### ルーム (room) — Ayame の room

Ayame の呼び方にそろえて「ルーム」と呼ぶ（以前は「チャネル」）。Ayame の roomId は `ayame_room_id`（画面では「ルームID」）、
ルームの行を指す列は `room_id` にして、同じ名前にならないようにしている。

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| ルーム名 | name | text | ✓ | ✓ | ✓ | 一意 |
| ルームID | ayame_room_id | text | ✓ | ✓ | ✓ | 一意。Ayame の roomId。Kazami はこの値で register する |
| グループ | group_id | ref(group) | ✓ | ✓ | ✓ | このグループのユーザーにだけ見える |
| サーバ | server_id | ref(server) |  | ✓ |  | 空なら既定のサーバ。既定のサーバもなければつなげない（画面に「サーバ未設定」と出す） |
| メモ | note | longtext |  |  |  | |

### デバイス (device) — Kazami 端末

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| デバイス名 | name | text | ✓ | ✓ | ✓ | 一意 |
| ルーム | room_id | ref(room) |  | ✓ | ✓ | 端末がつながるルーム。空なら端末は待機する |
| デバイスID | device_id | text |  | ✓ | ✓ | 端末が名乗る ID（identifierForVendor）。登録するまで空。一意 |
| 公開鍵 | public_key | text |  |  |  | QR で登録した P-256 の公開鍵 |
| 登録日時・最終接続・接続元 | enrolled_at / last_seen_at / last_ip | datetime / text |  | ✓ |  | |
| メモ | note | longtext |  |  |  | |

### 画像 (image)

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| ルーム | room_id | ref(room) |  | ✓ | ✓ | 手動の取り込みは空。ルームを消しても画像は残す |
| ルーム名（控え） | room_name | text |  |  | ✓ | 撮像時点の名前 |
| グループ | group_id | ref(group) | ✓ |  | ✓ | 撮像時点のルームのグループ。手動の取り込みは選んだグループ |
| 撮像した人 | captured_by | user |  |  |  | 撮像を頼んだ人・取り込んだ人 |
| 撮像日時 | captured_at | datetime | ✓ | ✓ | ✓ | 日付フォルダもこれで決める |
| 元のファイル名 | source_name | text |  |  |  | |
| 幅・高さ・容量 | width / height / size_bytes | number | ✓ |  |  | |
| タグ | tags | text[] |  | ✓ | ✓ | 1 枚に 20 個まで、1 つ 50 文字まで。全角・半角、大文字・小文字の違いは同じタグとみなす（NFKC ＋ casefold で比べる。最初の書き方を残す）。先頭の `#` は外す |
| メモ | note | longtext |  |  |  | |
| 図形 | markers | json |  |  |  | 楕円 `{type:"ellipse", x, y, width, height, rotation}`、多角形 `{type:"polygon", points:[{x, y}]}`、吹き出し `{type:"callout", x, y（指す先）, bx, by（本体の中心）, text}`。座標と大きさは画像の幅・高さに対する割合（小数 5 桁）。1 枚に 100 個まで、多角形の頂点は 3〜500 個 |
| お気に入り | favorite | bool |  | ✓ | ✓ | 既定=false |
| 取得元 | source | enum(camera,upload) | ✓ |  |  | upload は以前の「手元の画像の取り込み」で入れたもの（取り込みの機能はなくした） |

### アルバム (album)

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| 名前 | name | text | ✓ | ✓ |  | 一意 |
| 説明 | description | longtext |  |  |  | |
| グループ | group_id | ref(group) | ✓ | ✓ |  | このグループの画像だけを入れられる。所属が 1 つなら選ばせない |

### アルバムの画像 (album_item)

| 項目 | key | 型 | 必須 | 一覧 | 検索 | 備考 |
|---|---|---|---|---|---|---|
| アルバム | album_id | ref(album) | ✓ |  |  | |
| 画像 | image_id | ref(image) | ✓ |  |  | アルバム内で一意。画像を消すと一緒に外れる |

## マスタ

ユーザー・グループ・サーバ・ルーム・デバイス。どれもマスター画面（`/masters/<種類>`）で編集する。
変更はすべて監査ログ（`data/audit_logs.jsonl`）に残す。監査ログは `AUDIT_LOG_RETENTION_DAYS`（既定 90 日）を過ぎたら消す（起動時と、そのあと 1 時間に 1 回まで。gunicorn の worker どうしはファイルロックでぶつからないようにする）。IP アドレスなどを、不正利用への対応に要る間だけ持つため。

## 権限

ロールは機能キーの既定値のセット。画面の出し分けも API の検査も機能キーで行う。

| 機能キー | 内容 | admin | device_admin | power | user |
|---|---|:-:|:-:|:-:|:-:|
| can_view | 映像・ライブラリ・アルバムを見る、撮像、通話、お気に入り | ✓ | ✓ | ✓ | ✓ |
| can_edit | タグ・メモ・図形・アルバムの編集、画像の削除 | ✓ | ✓ | ✓ | |
| can_manage_devices | サーバ・ルーム・デバイスの編集、登録 QR の発行 | ✓ | ✓ | | |
| can_manage_users | ユーザー・グループの編集、監査ログの閲覧 | ✓ | | | |

見られる範囲は所属グループで決める（ルーム・画像・アルバム）。admin は全グループを見る。
見られないグループのものは「見つかりません」と答える（存在を伏せる）。

## 画面

- **ルーム一覧**（既定画面 `/`）— 見られるルームのカード（複数グループならグループごと）。カードから単一ビューを開く
- **単一ビュー**（`/view/:roomId`）
  - 接続・切断、映像、接続状態、RTT、受信中のコーデック・解像度・フレームレート
  - マイク（最初はオフ）とスピーカー（最初はオフ）
  - 撮像ボタン。撮像時に付けるメモを入れておける（タグは撮ったあとにライブラリで付ける）
  - カメラの調整: 倍率（プリセットとスライダー）、フォーカス（オートか位置）、色合い（オートか色温度）、露出補正。Kazami の画面で変えた値も反映される
  - 映像をダブルクリックすると、その位置にフォーカスと露出を合わせる（Kazami の画面をタップしたときと同じ。黄色い枠を出し、Kazami の画面にも「遠隔でフォーカスを合わせました」と出す）
  - 撮像した画像の直近のサムネイル（クリックで詳細）
- **マルチビュー**（`/multi`）
  - ルームを選んでタイルに並べる。タイルの大きさは小・中・大、1 枚を最大化
  - タイルごとに接続・切断と撮像。受信は映像だけ
- **ライブラリ**（`/library`）
  - 左: ルーム → 日付のツリー（件数つき）、基準日と期間（1・7・30・90 日）
  - 中央: 仮想スクロールのサムネイル一覧。クリックで 1 枚、Shift で範囲、Ctrl / Cmd で追加・解除
  - フィルタ: タグ（使われているタグをチップで並べ、押して絞り込む。複数選ぶと、いずれかのタグを持つ画像）、お気に入りのみ
  - サムネイルの左上にタグを 3 つまで `#タグ` で重ねて出す（それ以上は `+N`）。選択は右上の丸
  - 選択・絞り込みの操作は 1 行にまとめる（全選択／選択解除、タグ付け、アルバムに追加、ZIP、削除、お気に入り、タグのチップ）
  - 選択した画像への操作: アルバムに追加（押すと追加先のアルバムを選ぶダイアログ。アルバムを作るのはアルバムのタブ）、タグ付け（追加・置き換え・外す。使われているタグをチップで選び、無いものはカンマ区切りで入力）、ZIP ダウンロード、削除
  - 編集権限が無い人には、タグ付け・アルバムに追加・削除を出さない
- **画像の詳細**（ダイアログ）— 拡大表示、前後の画像へ移動、スライドショー、お気に入り、タグの表示（付け外しはライブラリ・アルバムの「タグ付け」）、メモの編集、図形の描画、ダウンロード、削除
  - 図形: 楕円の追加、多角形の描画（クリックで頂点、最初の頂点の近くか Enter で閉じる）、ドラッグで移動、Shift ＋ドラッグで回転、楕円は右下の丸で大きさ、多角形は頂点のドラッグ・追加・削除。保存するまでは画像に反映しない。描いている間は前後の画像に移れない
  - 吹き出し: 文字（改行可、200 文字まで）を書き込める。本体をドラッグで移動、しっぽの先（青い丸）をドラッグで指す先を変える。文字は詳細の右の欄で書き換える。文字の大きさは画像の表示幅に合わせて変わる
- **アルバム**（`/albums/:albumId`）
  - アルバムの画像一覧。サムネイルにタグを重ねて出す（ライブラリと同じ）
  - 選択・絞り込みの操作は 1 行にまとめる（全選択／選択解除、タグ付け、アルバムから外す、タグのチップで絞り込み）。ライブラリと同じ
  - ZIP 書き出し: アルバムの画像をフォルダを作らずにまとめる（ファイル名は撮像日時・ルーム名・画像 ID）
- **マスター**（`/masters/<members|users|groups|servers|rooms|devices|audit>`）— 権限のあるタブだけを出す。グループ管理者にはメンバー・ルーム・デバイスだけを出し、自分のグループのものだけを扱わせる
  - デバイスでは登録 QR（5 分・1 回限り）を出す。QR に入れる kazayomi の URL はサーバが決める（`PUBLIC_BASE_URL`、無ければ画面を開いている URL）。画面では変えられない
- **ログイン**（`/login`）— Google でサインイン（未登録のアカウントでも、招待が届いていれば参加できる）。`APP_ENV=local` のときは省き、画面上部に警告を出す

## ログイン

- Google Identity Services の ID トークンを `/auth/google` で検証し、ユーザーマスターに登録済みで有効な人だけを通す
- セッションは HttpOnly の Cookie（SameSite=Lax、12 時間）。セッションにはメールアドレスだけを持ち、ロールと所属グループはリクエストのたびに読み直す
- 最初の管理者は `BOOTSTRAP_ADMIN_EMAILS` で登録する。自分の管理者権限は外せず、最後の管理者は消せない
- **グループを作れるのはアプリの管理者だけ**（マスター › グループ）。誰でも作れると、誰でもメールアドレスを登録できてしまうため。作ったら、マスター › メンバーで最初のグループ管理者を招待する
- **招待された人**: 未登録のアカウントで Google サインインしても、招待が届いていれば、ログイン画面に招待が出る。「参加する」で、そのグループの招待された役割のメンバーになり、そのままログインする。メールアドレスは Google で確かめたもの（セッションに 15 分だけ持つ）を使い、画面からは受け取らない
  - 招待がない人は入れない。登録されていない人のログイン失敗は、メールアドレスなしで記録する。無効にされたユーザーには招待を出さない
  - ログインできなかったときの画面のメッセージは、理由（トークンを確かめられない・登録されていない・止められている）によらず「ログインできませんでした。」だけにする。どのアドレスが登録されているかを探られないように。理由はログと監査ログに残す（設定の不備だけは、運用する人が気付けるようそのまま出す）
- **グループでの役割**: 所属グループごとに、グループ管理者（owner）・編集者（editor）・閲覧者（viewer）を持つ。あるグループでできることは、全体のロールとグループでの役割の強いほう
  - グループ管理者: そのグループのメンバーの招待・役割の変更・外すこと、ルーム・デバイスの登録と登録 QR。サーバの編集・ユーザーとグループのマスター・監査ログはアプリの管理者だけ
  - グループには、いつも 1 人以上の有効なグループ管理者を残す
  - **グループの削除**: グループ管理者（とアプリの管理者）は、マスター › メンバーの下の「グループを削除」で、グループを中身ごと消せる。ルーム・デバイス・画像（rustfs のファイルも）・アルバム・招待を消す。このグループにしか入っておらず全体のロールが閲覧者の人は、アカウントも消す（消した本人も含む。そのあとログアウトする）。ほかのグループにも入っている人と、アプリの管理者がロールを付けた人は、グループから外すだけ。確認の画面で中身の数を見せ、グループ名を打ち込ませる。既定のグループ（`default`）は消せない。消すと、作った人はまた 1 つ作れる
  - 移行前からいる人のグループでの役割は閲覧者にしてあり、全体のロールで今までどおり動く
- **招待**: グループ管理者がマスター › メンバーでメールアドレスと役割を指定する。メールは送らないので、画面に出る案内文（ログイン画面の URL とアドレス）を本人に伝える。14 日で切れる。登録済みの人には、画面右上の封筒のボタンに届き、そこで参加するか断るかを選ぶ
- 作成・招待・参加・役割の変更・外すことは、すべて監査ログに残す
- `APP_ENV=local` のときだけログインを省く。開いた人は誰でも開発ユーザー（`DEV_USER_EMAIL`、既定は管理者）として扱う。クラウド上でこの設定のまま起動しようとすると起動を止める
  - 使うのは開発と、手元で試すとき。Google ログインは http では `localhost` でしか使えず、IP アドレスの URL も登録できないので、`http://<PC の IP>:8080` で開く手元の環境では使えない
  - 初めて起動したときは、すぐ試せるよう、既定のサーバ（`PUBLIC_BASE_URL` のホストの 3000 番の Ayame）・ルーム・デバイスを 1 つずつ作る。作るのは 1 回だけ（`app_settings` に記録し、消しても作り直さない）。サーバかルームがすでにある DB では作らない
- Google ログインで動かすには、https で開けるドメインが要る（リバースプロキシや Cloudflare Tunnel などで 8080 番につなぐ）

## 端末登録と設定の配信

共有の鍵（PSK）は使わない。

1. マスター › デバイスで登録 QR を出す。中身は `{"v":1,"api":"<kazayomi の URL>","token":"<登録トークン>","name":"<デバイス名>"}`
2. Kazami は端末の中で P-256 の署名鍵を作る（実機は Secure Enclave）。`POST /api/devices/enroll` に `token`・`device_id`・`device_pub`（x963 の Base64）・`signature` を送る
   - 署名する中身: `kazayomi-enroll-v1` `\n` token `\n` device_id `\n` 公開鍵
3. 起動のたびに `POST /api/devices/challenge` → `POST /api/devices/token`（署名する中身: `kazayomi-auth-v1` `\n` challenge `\n` device_id）
   - 返すもの: `access_token`（12 時間）、`room`（name・ayame_room_id）、`signaling_url`、`signaling_key`（= access_token）、`can_upload_captures`（本体の撮像ボタンで撮った画像を送れるか。この版はいつも true。Kazami は false のとき撮像ボタンを出さない）
4. Kazami は受け取った設定でつなぐ。撮像した画像は登録した kazayomi へ送る。つなぐ先を Kazami で手入力する欄は持たない。登録していない Kazami はつながない
5. 端末をなくした・入れ替えるときは、マスター › デバイスで「登録を外す」。次の接続から入れなくなる

## シグナリングの中継（ブラウザ）

ブラウザは Ayame に直接つながず、画面と同じ Origin の `/api/rooms/{id}/signaling`（WebSocket）につなぐ。kazayomi がルームのサーバへ中継する。

- 理由: Chrome の Local Network Access により、`http://<IP>` で開いた画面（安全でないコンテキスト）からは、別の Origin（別のポートの Ayame）への WebSocket が止められる
- ログインと、ルームを見られることを確かめてから中継する。Origin が画面と違う接続は断る（Cross-Site WebSocket Hijacking 対策）
- 閉じるときのコード: 4401 未ログイン、4403 Origin が違う、4404 見られないルーム、4502 Ayame に届かない
- 中身には手を加えない。入室の可否は Ayame の認証 Webhook が決める。Kazami は今までどおり Ayame に直接つなぐ
- Ayame に届く必要があるのは kazayomi と Kazami だけ。サーバの URL は両方から届くものにする

## Ayame の認証（ルームを守る）

Ayame の `authn_webhook_url` を `http://127.0.0.1:8080/api/ayame/authn` に向ける。Ayame は kazayomi と同じネットワーク名前空間で動かす（compose では、名前空間とポートだけを持つ `net` コンテナに両方を `network_mode: service:net` で同居させる。片方を作り直しても、もう片方が切れないようにするため）。

- Webhook は `AYAME_WEBHOOK_ALLOWED_IPS`（既定 127.0.0.1・::1）からの呼び出しにだけ答え、それ以外には 403 を返す
- 転送のヘッダー（`X-Forwarded-For`・`Forwarded`・`X-Real-IP`）が付いた呼び出しは、接続元に関わらず断る。同じホストのリバースプロキシを通った外からのリクエストも 127.0.0.1 に見えるため
- `AYAME_WEBHOOK_SECRET` を設定したときは、`?key=` の一致も求める（任意）
- これで kazayomi をインターネットに公開しても、Webhook は外から呼べない
Ayame の取り決めどおり HTTP は常に 200 で返し、可否は `allowed` で伝える。

入室を許すとき、ルームのサーバ（なければ既定のサーバ）が `cloudflare` なら、応答に `iceServers` を付ける。Ayame はそれを `accept` に載せてブラウザと Kazami に渡す。

- Cloudflare の `generate-ice-servers` で TTL 24 時間の認証情報を発行し、サーバごとに 1 時間だけ使い回す（サーバを編集したら発行し直す）
- ポート 53 の URL はブラウザで使えないので除く
- 発行に失敗したら（3 秒で打ち切る）`stun:stun.cloudflare.com:3478` だけを渡す
- `ayame` のサーバでは `iceServers` を付けない（ブラウザも Kazami も既定の STUN を使う）

| signalingKey | 通すとき |
|---|---|
| ブラウザの入室チケット（`v1.` で始まる。1 分・1 回限り） | チケットを発行したルームと同じとき。チケットは、そのルームを見られるログイン中のユーザーにだけ、接続のたびに `POST /api/rooms/{id}/ticket` で出す |
| デバイスのアクセストークン | 登録済みのデバイスで、割り当てたルームと同じとき |

ルームIDを知っているだけでは入れない。登録していない Kazami も入れない。

## 撮像の流れ（Kazami の撮像ボタン）

1. Kazami の撮像ボタンで、エンコード前のフレームを JPEG にする
2. Kazami → `POST <登録した kazayomi の URL>/api/devices/images`（`Authorization: Bearer <デバイスのアクセストークン>`、multipart の `image` と `capturedAt`）
3. kazayomi は、そのデバイスに割り当てたルームとグループに保存する。撮像した人は `device:<デバイス名>`（画面では 端末「…」）。ルームが割り当てられていなければ断る

## 撮像の流れ（kazayomi から頼む）

1. ブラウザ → `POST /api/captures`（`room_id`、タグ、メモ）。そのルームを見られる人にだけ、撮像IDと使い捨てトークン（60 秒、1 回限り）を発行
2. ブラウザ → Kazami（DataChannel）: `{"type":"capture","captureId":"…","token":"…"}`
3. Kazami はエンコード前のカメラフレームを JPEG にする
4. Kazami → `POST <登録した kazayomi の URL>/api/captures/<captureId>/image`
   - ヘッダー `Authorization: Bearer <token>`、multipart の `image`（JPEG）と `capturedAt`（ISO 8601）
   - 送り先は登録した kazayomi に限る。メッセージで届いた URL には送らない
5. サーバーは保存してサムネイルを作り、`{"id": "<imageId>", ...}` を返す
6. Kazami → ブラウザ（DataChannel）: `{"type":"captureResult","captureId":"…","ok":true,"imageId":"…"}`

ブラウザはトークンの期限が切れても結果が来なければ、失敗として表示する。

## DataChannel の取り決め

- ラベル `ctrl`、`negotiated: true`、`id: 0`、ordered。両側が PeerConnection を作った直後に作る（どちらが offer を出してもつながるように）
- メッセージは UTF-8 の JSON 1 つ。`type` で種類を分ける

| type | 向き | 中身 |
|---|---|---|
| `hello` | Kazami → ブラウザ | `app`（"kazami"）、`version`、`deviceName`、`capabilities`（例: `["capture", "captureDirect", "camera", "pointer", "chat"]`） |
| `capture` | ブラウザ → Kazami | `captureId`、`token` |
| `captureResult` | Kazami → ブラウザ | `captureId`、`ok`、`imageId`（成功時）、`message`（失敗時） |
| `cameraGet` | ブラウザ → Kazami | なし。`cameraState` が返る |
| `cameraSet` | ブラウザ → Kazami | `zoom`（倍）、`focus`（0: 近い〜1: 遠い、か `"auto"`）、`focusPoint`（`{x, y}`。ブラウザで見ている映像の上の位置を 0〜1 で。その位置にフォーカスと露出を合わせる）、`whiteBalance`（色温度 K、か `"auto"`）、`exposure`（露出補正 EV）。指定したものだけ変える |
| `cameraState` | Kazami → ブラウザ | `adjustable`、`camera`（例: "広角 1920x1080 30fps"）、`zoom`・`maxZoom`・`zoomPresets`、`focus`・`manualFocus`、`whiteBalance`・`manualWhiteBalance`・`whiteBalanceRange`、`exposure`・`exposureRange`。オートのものは `null`。DataChannel がつながったとき、`cameraSet` のあと、Kazami の画面で調整したとき（0.2 秒落ち着いてから）に送る |
| `pointer` | ブラウザ → Kazami | `x`・`y`（映像の幅・高さに対する割合 0〜1、左上が原点）、`color`（"#RRGGBB"）。ブラウザで映像をドラッグしている間、30ms ごとに送る。Kazami はプレビューの同じ位置に点を出し、1 秒で消す（配信する映像には入らない） |
| `chat` | ブラウザ → Kazami | `id`、`text`（200 文字まで）、`from`（送った人の名前）。Kazami はプレビューの下のほうに吹き出しで出し、振動と音で知らせる。4 通まで並べ、30 秒で（タップで先に）消す |
| `chatRead` | Kazami → ブラウザ | `id`。`chat` を画面に出したら返す。ブラウザは送った吹き出しに「既読」を付ける |

Kazami は、画像を kazayomi に送らず DataChannel でブラウザに渡す撮像（`captureDirect`・`captureChunk`・`captureDone`）にも対応しているが、ゲストのルーム向けのもので、この版では使わない。
知らない `type` は無視する。`capabilities` に `"camera"` が無い Kazami には、カメラの調整を出さない。`"pointer"` が無い Kazami には、ポインターのボタンを出さない。`"chat"` が無い Kazami には、メッセージを送れない（入力欄を使えなくする）。
ブラウザはスライダーを動かしている間、`cameraSet` を 0.12 秒ごとにまとめて送る（送りすぎて詰まらないように）。
RTT は DataChannel の往復ではなく、WebRTC の統計（選ばれた候補ペアの `currentRoundTripTime`）から出す。

## API

ログインが要らないのは `/healthz`、`/login`・`/auth/*`、Kazami が呼ぶもの（`/api/devices/enroll|challenge|token|images`、`/api/captures/{id}/image`）、Ayame が呼ぶ `/api/ayame/authn` だけ。

| メソッド・パス | 権限 | 内容 |
|---|---|---|
| `GET /api/me` | ログイン | ユーザー、ロール、機能キー、見られるグループ、認証モード |
| `GET /api/config` | ログイン | 版、撮像トークンの有効期間 |
| `GET /api/rooms`、`GET /api/rooms/{id}` | can_view | 見られるルーム |
| `POST /api/rooms/{id}/ticket` | can_view | Ayame の入室チケット |
| `WS /api/rooms/{id}/signaling` | can_view | Ayame へのシグナリングの中継 |
| `POST /api/captures`、`GET /api/captures/{id}` | can_view | 撮像トークンの発行・状態 |
| `POST /api/captures/{id}/image` | 撮像トークン | Kazami からのアップロード |
| `GET /api/images`（`room_id`・`room_name`・`group_id`・期間・タグ・お気に入り）、`/summary`、`/tags` | can_view | ライブラリ |
| `GET /api/images/{id}`、`/file`、`/thumb`、`POST /api/images/zip`、`/album-usage` | can_view | |
| `PATCH /api/images/{id}` | can_view（お気に入りだけ）／ can_edit | |
| `POST /api/images/tags/batch`、`/delete` | can_edit | |
| `GET /api/albums`、`/{id}`、`/{id}/items`、`/{id}/export` | can_view | |
| `POST/PATCH/DELETE /api/albums…`、`/items`、`/items/update`、`/items/remove`、`/split` | can_edit | |
| `/api/masters/users`、`/api/masters/groups`（作成・変更・削除） | can_manage_users | |
| `GET /api/masters/groups` | can_manage_users か can_manage_devices | ルーム編集の選択肢 |
| `/api/masters/servers`、`/rooms`、`/devices`、`/devices/{id}/enrollment` | can_manage_devices | |
| `GET /api/audit-logs` | can_manage_users | 監査ログ |
| `POST /api/devices/enroll`、`/challenge`、`/token` | 端末の署名 | 端末登録と認証 |
| `POST /api/devices/images` | デバイスのアクセストークン | Kazami の撮像ボタンで撮った画像 |
| `POST /api/ayame/authn` | （Ayame） | 認証 Webhook |

エラーは `{"error": "利用者向けの日本語メッセージ", "status_code": …}` に揃える。

## 運用

- 利用者: 数名、同時利用 数名
- 件数の見込み: 1 日数百枚、累計数万枚 → **保存方式: SQLite（メタデータ）＋ rustfs（画像・サムネイル）**
- デプロイ先: 手元の PC か社内のサーバで docker compose
- ログイン: Google（ユーザーマスターに登録した人だけ。https のドメインが要る）。手元で試すときは `APP_ENV=local` で省く
- 削除の扱い: 物理削除（確認ダイアログを出す）
- 既存データの移行: スキーマの版（PRAGMA user_version）で順に当てる。v2 でカメラをチャネルに改めて既定のグループに入れ、v4 でチャネルをルームに改めた（`channels` → `rooms`、`room_id` → `ayame_room_id`、`channel_id` → `room_id`）
- 通知: 不要

## 取り込まないもの

録画・動画の保存、撮像の予約、画像の自動判定（学習・推論）、データセットの版の管理。

## 進め方

| 段階 | 内容 |
|---|---|
| P0 | 仕様書、雛形、compose（Ayame ＋ kazayomi） |
| P1 | Ayame の接続処理と単一ビュー（映像・音声） |
| P2 | 画像 API とライブラリ画面 |
| P3 | Kazami の改修（DataChannel・撮像・アップロード）と撮像ボタン |
| P4 | マルチビュー |
| P5 | アルバム（タグで絞り込み、ZIP） |
| M1 | ログイン、ユーザー・グループのマスター、全 API の権限検査、監査ログ |
| M2 | サーバ・ルーム（当時はチャネル）のマスター。カメラを移行し、画像・アルバムにグループを付ける |
| M3 | デバイスのマスター、登録 QR、チャレンジ認証、設定の配信（Kazami に QR 読み取りと自動設定） |
| M4 | Ayame の認証 Webhook（デバイスのトークンとブラウザの入室チケット） |
| C1 | DataChannel でのカメラの遠隔操作（倍率・フォーカス・色合い・露出）、本番（k3s） |
| G1 | グループごとの役割と招待、グループの削除、容量の上限、既定のサーバ |
| G2 | ゲスト（ニックネームだけで一時的なルーム、ブラウザへの撮像、再開コード）、利用規約・プライバシーポリシー。のちに別の版へ移し、この版からは外した（O1） |
| O1 | オンプレミス専用にする。ゲスト・利用規約・プライバシーポリシーを外し、ログインの失敗のメッセージを 1 つにまとめる。登録 QR は 5 分 |
| O2 | 公開の準備。手元で試す手順（`APP_ENV=local` と初期データ）、compose の `net` コンテナ、第三者のライセンス文の同梱 |

## セキュリティ

- 撮像トークンは 1 回限り・60 秒。保存するのは SHA-256 だけ。違うトークンで叩かれても、正しい撮像は潰さない
- CSP の `connect-src` は `'self'`、Google ログイン、Ayame のシグナリング（マスターのサーバの URL）の Origin だけを許す。`ws:` / `wss:` を丸ごとは許さない
- ログイン画面のスクリプトもインラインにせず別ファイルにする（`script-src 'self'` のまま動かすため）
- 登録トークン・チャレンジ・入室チケット・アクセストークンは Valkey に TTL 付きで置き、保存するのは SHA-256 だけ。署名を確かめてから使い切る
- 端末の秘密鍵は端末の外に出ない。サーバーのデータが漏れても端末になりすませない
- `Permissions-Policy` はマイクだけ自分自身に許す（通話のため）
- アルバムのラベル（v5 まで）は v6 の移行で画像のタグに移した。train / val の分割は v7、分類に使うタグは v8 でなくした（アルバムでもライブラリと同じくタグで絞り込む）

## 決めていないこと

- 撮像の解像度 — Kazami の取り込み設定（最大 1920x1080）のフレームを使う。高解像度が要るなら `AVCapturePhotoOutput` を後で足す
- TURN — 既定は STUN のみ。外部のサービスに頼れるなら Cloudflare TURN（サーバの種類 cloudflare）を使える。外に出したくないなら coturn などを Ayame と並べて置くことを検討する
- https — Google ログインには https のドメインが要る。自己署名の証明書で配信する場合、iPhone から送るときは Kazami の証明書ピン留めを使う（公的な証明書なら要らない）
