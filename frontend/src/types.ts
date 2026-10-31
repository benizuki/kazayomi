// バックエンドのレスポンス型はここに集約する。
// API を変えたらこのファイルを直す、という一箇所ルールにしておくと、
// 型エラーが「直すべき場所の一覧」として機能する。

export interface AppConfig {
  version:                   string
  capture_token_ttl_seconds: number
}

// ── ログイン・権限 ─────────────────────────────────
export type Role = 'admin' | 'device_admin' | 'power' | 'user'

export interface Permissions {
  can_view:           boolean
  can_edit:           boolean
  can_manage_devices: boolean
  can_manage_users:   boolean
  can_manage_members: boolean
}

/** グループでの役割。全体のロールとあわせて、強いほうが効く */
export type GroupRole = 'owner' | 'editor' | 'viewer'

/** 自分あての、まだ受けていない招待 */
export interface PendingInvitation {
  id:         string
  group_name: string
  role:       GroupRole
  expires_at: string
}

export interface GroupRef {
  id:   string
  name: string
}

export type AuthMode = 'google' | 'dev-bypass'

export interface MeResponse {
  user:        { email: string; name: string; picture: string }
  role:        Role
  permissions: Permissions
  groups:      GroupRef[]
  all_groups:  boolean
  auth_mode:   AuthMode
  /** 全体のロールの権限（permissions はどれかのグループで持っている権限） */
  global_permissions: Permissions
  group_roles: Record<string, GroupRole>
  invitations: PendingInvitation[]
}

// ── マスター ───────────────────────────────────────
export interface UserRecord {
  id:            string
  email:         string
  name:          string
  role:          Role
  enabled:       boolean
  group_ids:     string[]
  group_roles:   Record<string, GroupRole>
  permissions:   Permissions
  last_login_at: string | null
  created_at:    string
  updated_at:    string
}

export type UserInput = Pick<UserRecord, 'email' | 'name' | 'role' | 'enabled' | 'group_ids'>

/** グループのメンバー（グループ管理者が見る） */
export interface GroupMember {
  user_id:       string
  email:         string
  name:          string
  role:          GroupRole
  global_role:   Role
  enabled:       boolean
  last_login_at: string | null
}

export interface GroupInvitation {
  id:         string
  group_id:   string
  group_name: string
  email:      string
  role:       GroupRole
  invited_by: string
  created_at: string
  expires_at: string
  expired:    boolean
}

export interface Group {
  id:            string
  name:          string
  room_count: number
  user_count:    number
  image_count:   number
  /** 画像とサムネイルの大きさの合計（バイト） */
  usage_bytes:   number
  /** 容量の上限（バイト）。null は無制限 */
  quota_bytes:   number | null
  created_at:    string
  updated_at:    string
}

export interface GroupInput {
  id:          string
  name:        string
  quota_bytes: number | null
}

export interface AppSettings {
  /** マスター › グループで新しく作るグループの容量の上限。null は無制限 */
  default_group_quota_bytes: number | null
}

/** ayame: Ayame だけ（既定の STUN）。cloudflare: シグナリングは Ayame、TURN は Cloudflare で発行する */
export type ServerKind = 'ayame' | 'cloudflare'

export interface Server {
  id:            string
  name:          string
  signaling_url: string
  kind:          ServerKind
  /** Cloudflare の TURN キー ID（kind が cloudflare のとき） */
  turn_key_id:   string
  /** API トークンを設定済みか。トークンそのものは返らない */
  turn_api_token_set: boolean
  note:          string
  /** 既定のサーバ。サーバを選んでいないルームが使う（1 つだけ） */
  is_default:    boolean
  room_count: number
  created_at:    string
  updated_at:    string
}

export type ServerInput = Pick<Server, 'name' | 'signaling_url' | 'kind' | 'turn_key_id' | 'note' | 'is_default'> & {
  /** 空のまま保存すると、今のトークンをそのまま使う */
  turn_api_token: string
}

// ルーム（Ayame のルーム）。Kazami 1 台ぶんの映像の入口
export interface Room {
  id:            string
  name:          string
  ayame_room_id:       string
  group_id:      string
  group_name:    string
  server_id:     string | null
  server_name:   string
  /** サーバのシグナリング URL。サーバ未設定なら既定値 */
  signaling_url: string
  note:          string
  sort_order:    number
  created_at:    string
  updated_at:    string
}

export type RoomInput = Pick<Room, 'name' | 'ayame_room_id' | 'group_id' | 'server_id' | 'note'>

// デバイス（Kazami 端末）
export interface Device {
  id:           string
  name:         string
  room_id:   string | null
  room_name: string
  ayame_room_id:      string
  group_id:     string | null
  group_name:   string
  /** 端末が名乗る ID。QR で登録するまでは空 */
  device_id:    string
  enrolled:     boolean
  enrolled_at:  string | null
  last_seen_at: string | null
  last_ip:      string
  note:         string
  created_at:   string
  updated_at:   string
}

export type DeviceInput = Pick<Device, 'name' | 'room_id' | 'note'>

export interface EnrollmentTicket {
  token:             string
  name:              string
  expires_at:        string
  suggested_api_url: string
}

export interface AuditLog {
  timestamp:    string
  category:     string
  event:        string
  outcome:      string
  email:        string | null
  target?:      string
  detail?:      string | null
  source_ip?:   string
  status_code?: number
}

// ── 画像 ───────────────────────────────────────────
export type ImageSource = 'camera' | 'upload'

export interface ImageRecord {
  id:           string
  room_id:   string | null
  /** 撮像時点のルーム名（ルームを消しても残る）。手動の取り込みは空 */
  room_name: string
  group_id:     string
  /** 撮像を頼んだ人・取り込んだ人のメールアドレス */
  captured_by:  string
  captured_at:  string
  date_key:     string
  source:       ImageSource
  source_name:  string
  width:        number
  height:       number
  size_bytes:   number
  tags:         string[]
  note:         string
  favorite:     boolean
  /** 画像に描いた図形。座標と大きさは画像の幅・高さに対する割合（0〜1） */
  markers:      Marker[]
  created_at:   string
  updated_at:   string
}

/** 楕円。中心（x, y）と、回転させる前の幅・高さ。rotation は度 */
export interface EllipseMarker {
  type:     'ellipse'
  x:        number
  y:        number
  width:    number
  height:   number
  rotation: number
}

/** 多角形（頂点は 3 つ以上） */
export interface PolygonMarker {
  type:   'polygon'
  points: { x: number, y: number }[]
}

/** 吹き出し。x, y は指し示す先（しっぽの先）、bx, by は吹き出しの中心。text は自由なコメント（改行可） */
export interface CalloutMarker {
  type: 'callout'
  x:    number
  y:    number
  bx:   number
  by:   number
  text: string
}

export type Marker = EllipseMarker | PolygonMarker | CalloutMarker

export interface ImageListResponse {
  items:       ImageRecord[]
  total:       number
  next_offset: number | null
}

export interface ImageSummaryRow {
  room_id:   string | null
  room_name: string
  date_key:     string
  count:        number
}

export interface TagCount {
  tag:   string
  count: number
}

export type TagMode = 'add' | 'replace' | 'remove'

// ── 撮像 ───────────────────────────────────────────
export interface CaptureTicket {
  capture_id: string
  token:      string
  expires_at: string
}

export interface CaptureStatus {
  capture_id: string
  status:     'pending' | 'done' | 'expired'
  image_id?:  string
}

// ── アルバム ───────────────────────────────────────

export interface Album {
  id:             string
  name:           string
  description:    string
  group_id:       string
  group_name:     string
  created_at:     string
  updated_at:     string
  item_count:     number
  cover_image_id: string | null
}

export interface AlbumItem {
  image:    ImageRecord
  added_at: string
}

// ── 共通のエラー形 ─────────────────────────────────
export interface ApiError {
  error:        string
  status_code?: number
}

// ── DataChannel（Kazami との取り決め。docs/app-spec.md を参照）──
export type ControlMessage =
  | { type: 'hello'; app: string; version?: string; deviceName?: string; capabilities?: string[] }
  | { type: 'capture'; captureId: string; token: string }
  | { type: 'captureResult'; captureId: string; ok: boolean; imageId?: string; message?: string }
  // ゲストのルーム: 画像をサーバに送らず、DataChannel でブラウザに直接受け取る
  | { type: 'captureDirect'; captureId: string }
  | { type: 'captureChunk'; captureId: string; index: number; count: number; data: string }
  | { type: 'captureDone'; captureId: string; ok: boolean; width?: number; height?: number; size?: number; capturedAt?: string; message?: string }
  // レーザーポインター。映像の上の位置（0〜1）を Kazami に送り、Kazami の画面に重ねて出す
  | { type: 'pointer'; x: number; y: number; color: string }
  // 文字のメッセージ。Kazami の画面に吹き出しで出し、出したら chatRead を返す
  | { type: 'chat'; id: string; text: string; from: string }
  | { type: 'chatRead'; id: string }
  | { type: 'cameraGet' }
  | ({ type: 'cameraSet' } & CameraSettings)
  | ({ type: 'cameraState' } & CameraState)

/** 遠隔で変えるカメラの設定。指定したものだけが変わる。focus・whiteBalance は 'auto' でオートに戻す */
export interface CameraSettings {
  zoom?:         number
  /** フォーカス位置（0: 近い 〜 1: 遠い） */
  focus?:        number | 'auto'
  /** この位置にフォーカスと露出を合わせる（映像の幅・高さに対する割合、左上が原点） */
  focusPoint?:   { x: number, y: number }
  /** 色温度（K） */
  whiteBalance?: number | 'auto'
  /** 露出補正（EV） */
  exposure?:     number
}

/** Kazami が知らせる、今のカメラの設定と変えられる範囲。オートのものは null */
export interface CameraState {
  adjustable:         boolean
  camera:             string
  zoom:               number
  maxZoom:            number
  zoomPresets:        number[]
  focus:              number | null
  manualFocus:        boolean
  whiteBalance:       number | null
  manualWhiteBalance: boolean
  whiteBalanceRange:  [number, number]
  exposure:           number
  exposureRange:      [number, number]
}
