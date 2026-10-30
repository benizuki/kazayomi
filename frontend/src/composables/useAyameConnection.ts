import { computed, getCurrentScope, onScopeDispose, readonly, ref, shallowRef } from 'vue'
import type { ControlMessage } from '@/types'

/**
 * Ayame（P2P）で Kazami の映像を受け取る接続 1 本ぶんの状態。
 *
 * 手順は kazami の test/viewer/index.html と同じ。
 * - 後から register した側が offer を出す（Ayame の仕様）。カメラが先にいればこちらから出し、
 *   いなければカメラが来るのを待って、カメラの offer に answer を返す
 * - 切れたら 2 秒後（拒否されたときは 10 秒後）に register からやり直す
 * - DataChannel は両側で negotiated: true, id: 0 で作る。どちらが offer を出してもつながるようにするため
 *
 * 呼ぶたびに別の接続になる（マルチビューのタイルごとに 1 本）。
 */

export type ConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'waiting'
  | 'negotiating'
  | 'connected'
  | 'reconnecting'
  | 'rejected'

export interface ConnectionStats {
  codec:     string
  width:     number
  height:    number
  fps:       number
  rttMs:     number | null
  audio:     string
  /** いま使っている ICE の経路。まだ決まっていなければ null */
  route:     ConnectionRoute | null
}

/** host: 直接 / srflx・prflx: STUN で穴を開けて直接 / relay: TURN で中継 */
export type CandidateType = 'host' | 'srflx' | 'prflx' | 'relay'

export interface ConnectionRoute {
  /** 経路の分類。どちらかが relay なら turn、どちらかが srflx/prflx なら stun、それ以外は direct */
  kind:        'direct' | 'stun' | 'turn'
  local:       CandidateType | ''
  remote:      CandidateType | ''
  /** 通信のプロトコル（udp / tcp） */
  protocol:    string
  /** TURN サーバまでのプロトコル（udp / tcp / tls）。relay のときだけ */
  relayProtocol: string
  /** 自分側の候補を作った STUN/TURN サーバの URL。ブラウザによっては取れない（Safari など） */
  serverUrl:   string
}

export function routeLabel(route: ConnectionRoute): string {
  if (route.kind === 'direct') return '直接'
  if (route.kind === 'stun') return 'P2P（STUN）'
  const side = route.local === 'relay' ? (route.remote === 'relay' ? '両側' : 'こちら側') : '相手側'
  const host = route.serverUrl ? route.serverUrl.replace(/^turns?:/, '').replace(/[:?].*$/, '') : ''
  const detail = [route.relayProtocol, host].filter(Boolean).join('・')
  return `TURN 中継（${side}${detail ? `・${detail}` : ''}）`
}

function classifyRoute(local: string, remote: string): ConnectionRoute['kind'] {
  if (local === 'relay' || remote === 'relay') return 'turn'
  if (['srflx', 'prflx'].includes(local) || ['srflx', 'prflx'].includes(remote)) return 'stun'
  return 'direct'
}

export interface AyameOptions {
  signalingUrl: () => string
  roomId:       () => string
  /**
   * register の signalingKey。kazayomi の入室チケット（1 分・1 回限り）を接続のたびに取ってくる。
   * Ayame の認証 Webhook がこれでルームに入ってよいかを確かめる。
   */
  signalingKey?: () => Promise<string>
  /** 受信する映像のコーデック（H264 / VP8 / VP9 / AV1）。空なら指定しない。 */
  codec?:       () => string
  /** 音声を扱うか。マルチビューのタイルは映像だけ受ける。 */
  audio:        boolean
}

type Hello = Extract<ControlMessage, { type: 'hello' }>

// kazayomi のシグナリング中継が閉じるときのコード（backend/api/signaling_api.py と合わせる）
const RELAY_CLOSE_REASONS: Record<number, string> = {
  4401: 'ログインが切れています。画面を開き直してください',
  4403: 'この画面からは中継を使えません（Origin が違います）',
  4404: 'このルームは見られません',
  4502: 'kazayomi から Ayame に届きません。サーバのシグナリングURLと Ayame の状態を確認してください',
  4503: 'このルームのシグナリングサーバが決まっていません。マスター › サーバで既定のサーバを決めるか、ルームでサーバを選んでください',
  4451: '利用規約への同意が必要です。画面を開き直してください',
}

/**
 * Ayame の clientId などに使う乱数。crypto.randomUUID は http://<IP> で開いた画面（安全でないコンテキスト）では
 * 使えないので、どこでも使える getRandomValues で作る。
 */
export function randomId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/** ブラウザから Ayame へは、画面と同じ Origin の kazayomi を経由してつなぐ（理由は backend/api/signaling_api.py）。 */
export function relaySignalingUrl(roomId: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/api/rooms/${encodeURIComponent(roomId)}/signaling`
}

const RECONNECT_DELAY_MS = 2000
const REJECT_RETRY_DELAY_MS = 10_000
const DEFAULT_ICE_SERVERS: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }]
const CONTROL_LABEL = 'ctrl'

export function useAyameConnection(options: AyameOptions) {
  const status = ref<ConnectionStatus>('idle')
  const rejectReason = ref('')
  const stream = shallowRef<MediaStream | null>(null)
  const stats = ref<ConnectionStats | null>(null)
  const remoteHasAudio = ref(false)
  const micOn = ref(false)
  const micError = ref<string | null>(null)
  const controlOpen = ref(false)
  const peerInfo = ref<Hello | null>(null)

  let ws: WebSocket | null = null
  let pc: RTCPeerConnection | null = null
  let dc: RTCDataChannel | null = null
  let micTrack: MediaStreamTrack | null = null
  let running = false
  let reconnectTimer: number | undefined
  let statsTimer: number | undefined
  let pendingCandidates: RTCIceCandidateInit[] = []
  let lastRouteKey = ''
  const controlHandlers = new Set<(message: ControlMessage) => void>()

  const statusText = computed(() => {
    switch (status.value) {
      case 'idle':         return '未接続'
      case 'connecting':   return 'シグナリングに接続しています'
      case 'waiting':      return 'カメラを待っています'
      case 'negotiating':  return '接続を確立しています'
      case 'connected':    return '受信中'
      case 'reconnecting': return '再接続を待っています'
      case 'rejected':
        // 満室（full）は、別の画面やタブがこのカメラを見ているとき
        if (rejectReason.value === 'full') {
          return '他の画面がこのルームを見ています（1 つのルームを見られるのは 1 か所だけです）。10 秒後にやり直します'
        }
        if (Object.values(RELAY_CLOSE_REASONS).includes(rejectReason.value)) {
          return `${rejectReason.value}。10 秒後にやり直します`
        }
        if (/AUTHN|WEBHOOK/i.test(rejectReason.value)) {
          return `Ayame の認証で断られました（${rejectReason.value}）。ルームの設定と権限を確認してください。10 秒後にやり直します`
        }
        return `接続できません（${rejectReason.value}）。10 秒後にやり直します`
    }
    return ''
  })

  // ── シグナリング ───────────────────────────────

  function send(message: Record<string, unknown>): void {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message))
  }

  async function openSocket(): Promise<void> {
    window.clearTimeout(reconnectTimer)
    status.value = 'connecting'
    let key = ''
    try {
      key = (await options.signalingKey?.()) ?? ''
    } catch (e) {
      // ルームが見られなくなった・ログインが切れたなど。少し待ってやり直す
      rejectReason.value = (e as Error).message
      status.value = 'rejected'
      scheduleReconnect(REJECT_RETRY_DELAY_MS)
      return
    }
    if (!running) return
    let socket: WebSocket
    try {
      socket = new WebSocket(options.signalingUrl())
    } catch {
      // URL の形式が違うときは同期的に投げられる
      rejectReason.value = 'シグナリングURLが正しくありません'
      status.value = 'rejected'
      scheduleReconnect(REJECT_RETRY_DELAY_MS)
      return
    }
    ws = socket
    socket.onopen = () => {
      const register: Record<string, unknown> = {
        type:        'register',
        roomId:      options.roomId(),
        clientId:    `kazayomi-${randomId()}`,
        ayameClient: 'kazayomi',
      }
      if (key) register.signalingKey = key
      send(register)
    }
    socket.onmessage = (event) => {
      if (socket !== ws) return
      handle(JSON.parse(String(event.data))).catch((error) => {
        console.error('ayame message handling failed', error)
        // 交渉の途中で失敗したら、つなぎ直すのがいちばん確実
        socket.close()
      })
    }
    socket.onclose = (event) => {
      if (socket !== ws) return
      ws = null
      closePeer()
      if (!running) {
        status.value = 'idle'
        return
      }
      // kazayomi の中継（/api/rooms/{id}/signaling）が理由を付けて閉じたとき
      const relayReason = RELAY_CLOSE_REASONS[event.code]
      if (relayReason) {
        rejectReason.value = relayReason
        status.value = 'rejected'
      }
      if (status.value === 'rejected') {
        scheduleReconnect(REJECT_RETRY_DELAY_MS)
      } else {
        status.value = 'reconnecting'
        scheduleReconnect(RECONNECT_DELAY_MS)
      }
    }
  }

  function scheduleReconnect(delay: number): void {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = window.setTimeout(() => { if (running) void openSocket() }, delay)
  }

  async function handle(message: Record<string, any>): Promise<void> {
    switch (message.type) {
      case 'ping':
        send({ type: 'pong' })
        break
      case 'accept':
        createPeer(message.iceServers)
        if (message.isExistClient) {
          // カメラが先にいる。こちらから offer を出す
          await sendOffer()
        } else {
          status.value = 'waiting'
        }
        break
      case 'reject':
        rejectReason.value = String(message.reason ?? '理由不明')
        status.value = 'rejected'
        break
      case 'offer': {
        if (!pc) createPeer()
        const peer = pc!
        status.value = 'negotiating'
        await peer.setRemoteDescription({ type: 'offer', sdp: message.sdp })
        configureTransceiversForAnswer(peer)
        await flushCandidates()
        const answer = await peer.createAnswer()
        await peer.setLocalDescription(answer)
        send({ type: 'answer', sdp: answer.sdp })
        break
      }
      case 'answer':
        await pc?.setRemoteDescription({ type: 'answer', sdp: message.sdp })
        await flushCandidates()
        break
      case 'candidate':
        if (!message.ice?.candidate) break
        if (pc?.remoteDescription) await pc.addIceCandidate(message.ice)
        else pendingCandidates.push(message.ice)
        break
      case 'bye':
        // カメラが抜けた。Ayame が WebSocket を閉じるので、onclose からやり直す
        closePeer()
        status.value = 'waiting'
        break
      default:
        break
    }
  }

  async function sendOffer(): Promise<void> {
    if (!pc) return
    status.value = 'negotiating'
    applyCodecPreference(pc.addTransceiver('video', { direction: 'recvonly' }))
    if (options.audio) {
      // マイクはまだ付けない。sendrecv にしておけば、あとで replaceTrack するだけで
      // 送り始められる（つなぎ直しが要らない）
      const audio = pc.addTransceiver('audio', { direction: 'sendrecv' })
      if (micTrack) await audio.sender.replaceTrack(micTrack)
    }
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    send({ type: 'offer', sdp: offer.sdp })
  }

  function configureTransceiversForAnswer(peer: RTCPeerConnection): void {
    for (const transceiver of peer.getTransceivers()) {
      const kind = transceiver.receiver.track.kind
      if (kind === 'video') {
        applyCodecPreference(transceiver)
      } else if (kind === 'audio') {
        if (options.audio) {
          transceiver.direction = 'sendrecv'
          if (micTrack) void transceiver.sender.replaceTrack(micTrack)
        } else {
          transceiver.direction = 'inactive'
        }
      }
    }
  }

  // 送信側（カメラ）は、受信側の SDP で先頭にあるコーデックで送る。指定のものを先頭に並べる
  function applyCodecPreference(transceiver: RTCRtpTransceiver): void {
    const codec = options.codec?.() ?? ''
    if (!codec || !transceiver.setCodecPreferences) return
    const codecs = RTCRtpReceiver.getCapabilities('video')?.codecs ?? []
    const preferred = codecs.filter((c) => c.mimeType.toLowerCase() === `video/${codec.toLowerCase()}`)
    if (!preferred.length) return
    transceiver.setCodecPreferences([...preferred, ...codecs.filter((c) => !preferred.includes(c))])
  }

  async function flushCandidates(): Promise<void> {
    const list = pendingCandidates
    pendingCandidates = []
    for (const candidate of list) await pc?.addIceCandidate(candidate)
  }

  // ── PeerConnection ─────────────────────────────

  function createPeer(iceServers?: RTCIceServer[]): void {
    closePeer()
    const servers = iceServers?.length ? iceServers : DEFAULT_ICE_SERVERS
    // 認証情報（username / credential）は出さない
    console.info('[ayame] ice servers', servers.flatMap((s) => (Array.isArray(s.urls) ? s.urls : [s.urls])))
    const peer = new RTCPeerConnection({ iceServers: servers })
    pc = peer
    lastRouteKey = ''
    peer.onicecandidate = (event) => {
      if (event.candidate) send({ type: 'candidate', ice: event.candidate.toJSON() })
    }
    peer.ontrack = (event) => {
      if (peer !== pc) return
      // 新しい MediaStream にすると、video 要素に渡し直されて確実に表示が切り替わる
      const tracks = [...(stream.value?.getTracks() ?? []), event.track]
      stream.value = new MediaStream(tracks)
      if (event.track.kind === 'audio') remoteHasAudio.value = true
    }
    peer.onconnectionstatechange = () => {
      if (peer !== pc) return
      if (peer.connectionState === 'connected') {
        status.value = 'connected'
      } else if (peer.connectionState === 'failed') {
        // ICE が通らなかった。シグナリングからやり直す
        ws?.close()
      }
    }

    const channel = peer.createDataChannel(CONTROL_LABEL, { negotiated: true, id: 0, ordered: true })
    dc = channel
    channel.onopen = () => { if (channel === dc) controlOpen.value = true }
    channel.onclose = () => { if (channel === dc) controlOpen.value = false }
    channel.onmessage = (event) => {
      const text = typeof event.data === 'string' ? event.data : new TextDecoder().decode(event.data as ArrayBuffer)
      let message: ControlMessage
      try {
        message = JSON.parse(text) as ControlMessage
      } catch {
        return
      }
      if (message.type === 'hello') peerInfo.value = message
      controlHandlers.forEach((handler) => handler(message))
    }

    window.clearInterval(statsTimer)
    statsTimer = window.setInterval(() => { void updateStats() }, 1000)
  }

  function closePeer(): void {
    pendingCandidates = []
    window.clearInterval(statsTimer)
    dc?.close()
    dc = null
    pc?.close()
    pc = null
    stream.value = null
    stats.value = null
    remoteHasAudio.value = false
    controlOpen.value = false
    peerInfo.value = null
  }

  async function updateStats(): Promise<void> {
    const peer = pc
    if (!peer) return
    const report = await peer.getStats()
    const codecs = new Map<string, string>()
    report.forEach((s) => { if (s.type === 'codec') codecs.set(s.id, String(s.mimeType).replace(/^(video|audio)\//, '')) })
    const next: ConnectionStats = { codec: '', width: 0, height: 0, fps: 0, rttMs: null, audio: '', route: readRoute(report) }
    report.forEach((s) => {
      if (s.type === 'inbound-rtp' && s.kind === 'video') {
        next.codec = codecs.get(s.codecId) ?? ''
        next.width = s.frameWidth ?? 0
        next.height = s.frameHeight ?? 0
        next.fps = Math.round(s.framesPerSecond ?? 0)
      } else if (s.type === 'inbound-rtp' && s.kind === 'audio') {
        next.audio = codecs.get(s.codecId) ?? ''
      } else if (s.type === 'candidate-pair' && s.nominated && s.state === 'succeeded' && s.currentRoundTripTime != null) {
        next.rttMs = Math.round(s.currentRoundTripTime * 1000)
      }
    })
    if (peer !== pc) return
    stats.value = next
    const route = next.route
    const key = route ? `${route.local}/${route.remote}/${route.protocol}/${route.relayProtocol}/${route.serverUrl}` : ''
    if (route && key !== lastRouteKey) {
      console.info(`[ayame] route: ${routeLabel(route)}`, route)
    }
    lastRouteKey = key
  }

  /** 選ばれている candidate-pair から経路を読む。transport の selectedCandidatePairId が無いブラウザでは nominated を見る */
  function readRoute(report: RTCStatsReport): ConnectionRoute | null {
    let pair: any = null
    report.forEach((s) => {
      if (s.type === 'transport' && s.selectedCandidatePairId) pair = report.get(s.selectedCandidatePairId) ?? pair
    })
    if (!pair) {
      report.forEach((s) => { if (!pair && s.type === 'candidate-pair' && s.nominated && s.state === 'succeeded') pair = s })
    }
    if (!pair) return null
    const local = report.get(pair.localCandidateId) ?? {}
    const remote = report.get(pair.remoteCandidateId) ?? {}
    return {
      kind: classifyRoute(local.candidateType ?? '', remote.candidateType ?? ''),
      local: local.candidateType ?? '',
      remote: remote.candidateType ?? '',
      protocol: local.protocol ?? '',
      relayProtocol: local.candidateType === 'relay' ? (local.relayProtocol ?? '') : '',
      serverUrl: local.url ?? '',
    }
  }

  // ── マイク ─────────────────────────────────────

  function audioSender(): RTCRtpSender | null {
    const transceiver = pc?.getTransceivers().find(
      (t) => t.receiver.track.kind === 'audio' && (t.direction === 'sendrecv' || t.direction === 'sendonly'),
    )
    return transceiver?.sender ?? null
  }

  async function setMic(on: boolean): Promise<void> {
    micError.value = null
    if (on) {
      if (!micTrack) {
        try {
          const media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
          micTrack = media.getAudioTracks()[0] ?? null
        } catch {
          micError.value = 'マイクを使えません。ブラウザのマイクの許可を確認してください（https か localhost で開く必要があります）。'
          return
        }
      }
      await audioSender()?.replaceTrack(micTrack)
      micOn.value = true
    } else {
      // 止めるときはトラックごと止める。enabled=false だけだと、ブラウザのマイク使用中の表示が消えない
      await audioSender()?.replaceTrack(null)
      micTrack?.stop()
      micTrack = null
      micOn.value = false
    }
  }

  // ── DataChannel ────────────────────────────────

  function sendControl(message: ControlMessage): boolean {
    if (!dc || dc.readyState !== 'open') return false
    dc.send(JSON.stringify(message))
    return true
  }

  function onControlMessage(handler: (message: ControlMessage) => void): () => void {
    controlHandlers.add(handler)
    return () => controlHandlers.delete(handler)
  }

  // ── 接続・切断 ─────────────────────────────────

  function connect(): void {
    if (running) return
    running = true
    rejectReason.value = ''
    void openSocket()
  }

  function disconnect(): void {
    running = false
    window.clearTimeout(reconnectTimer)
    const socket = ws
    ws = null
    socket?.close()
    closePeer()
    void setMic(false)
    status.value = 'idle'
  }

  if (getCurrentScope()) onScopeDispose(disconnect)

  return {
    status:         readonly(status),
    statusText,
    stream,
    stats:          readonly(stats),
    remoteHasAudio: readonly(remoteHasAudio),
    micOn:          readonly(micOn),
    micError,
    controlOpen:    readonly(controlOpen),
    peerInfo:       readonly(peerInfo),
    connect,
    disconnect,
    setMic,
    sendControl,
    onControlMessage,
  }
}

export type AyameConnection = ReturnType<typeof useAyameConnection>
