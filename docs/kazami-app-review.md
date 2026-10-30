# Kazami の App Store 審査メモ（下書き）

Kazami を App Store の審査に出すときに、App Store Connect の「App Review に関する情報」に書く内容。
審査担当者は kazayomi のゲスト機能（アカウントなしの一時的なルーム）で、Kazami のすべての機能を試す。

- `<KAZAYOMI_URL>` は本番の kazayomi の URL（例: `https://kazayomi.example.com`）に置き換える
- 「サインインが必要」はオフにする（Kazami にはログインがなく、ゲストで試せるため）。デモアカウント欄は空でよい
- メモ欄は 4,000 文字まで。下の英文は約 2,500 文字

## 出す前に確かめること

### kazayomi（サーバ）
- [ ] マスター › 設定 の「ゲストの利用」がオンになっている。審査中は止めない
- [ ] 既定のサーバを「Ayame + Cloudflare TURN」にしている。審査担当者は米国の社外ネットワークからつなぐので、直接つながらなくても TURN で映像が届くようにする
- [ ] 社外のネットワーク（携帯回線など）にある iPhone から、ゲストの手順を最後まで通せる
- [ ] `<KAZAYOMI_URL>/privacy` と `<KAZAYOMI_URL>/terms` がログインなしで開ける（App Store Connect のプライバシーポリシーの URL に使う）
- [ ] 同じ接続元からゲストを始められるのは 1 時間に 10 回まで（`GUEST_STARTS_PER_HOUR`）。審査担当者は同じ接続元から何度も試すことがあるので、審査中は上げておいてもよい

### Kazami（アプリ）
- [ ] 端末登録の画面の説明が「kazayomi のルームの画面か、マスター › デバイス で表示した登録 QR を読み取ってください」になっている版を出す（ゲストのルームの QR も読めることが分かるように直した）
- [ ] QR の中身を貼り付ける登録の方法は、シミュレータ向けのビルドにしかない。審査担当者は実機で QR を読むことになるので、メモには書いていない（ブラウザの画面を別の端末で開いて読んでもらう）
- [ ] ゲストのルームでは、Kazami 本体の撮像ボタンが出ない版を出す（kazayomi がトークンの応答で `can_upload_captures: false` を返し、Kazami がボタンを隠す）。kazayomi と Kazami の両方を新しくしておくこと。古い kazayomi だとボタンが出て、押すと保存を断る赤いメッセージが出る
- [ ] カメラ・マイク・ローカルネットワークを使う理由（Info.plist）が具体的に書かれている（今の文言で問題ない）
- [ ] App のプライバシー（App Store Connect）: 映像・音声は端末と視聴者のブラウザのあいだで P2P か TURN の中継で流れ、運営者は保存しない。収集するデータは「なし」か、診断データだけにする。kazayomi のプライバシーポリシーと矛盾しないこと
- [ ] 審査メモに添付する動画（1〜2 分）: ゲストを始める → QR を出す → Kazami で読む → 映像が出る → 撮像・メッセージ・ポインター

## メモ（英語。そのまま貼る）

```text
Kazami turns an iPhone or iPad into a remote monitoring camera for kazayomi, our web app for viewing on-site cameras from a browser. The app has no sign-in. It is paired with a kazayomi room by scanning a one-time QR code. Reviewers can test everything with kazayomi's guest mode. No account, email address or Google sign-in is needed.

Requirements: a computer (or a second device) with Chrome, Edge or Safari, and the iPhone/iPad running Kazami. The UI is in Japanese. The steps below give each button's label.

1. Start a guest room (browser)
 - Open <KAZAYOMI_URL>/login
 - Under "ゲストとして試す" (Try as guest), enter any nickname, tick the box to agree to the Terms and Privacy Policy, and press "ゲストとして始める" (Start as guest).
 - A temporary room opens. It shows a pairing QR code.

2. Pair Kazami (device)
 - Launch Kazami and allow camera access (and microphone access if asked).
 - Tap the gear icon (設定 / Settings) at the top right, then "QRコードで端末登録" (Register with QR code), and scan the QR code shown in the browser.
 - Tap "完了" (Done), then "保存" (Save). Kazami connects to the room automatically.

3. Try the features (browser)
 - Live video: the camera image appears in the browser within a few seconds.
 - Capture: press the shutter button in the browser. Kazami takes a full-resolution photo and sends it directly to the browser, which downloads it. Guest rooms never store images on our server, so in a guest room the Kazami app hides its own shutter button and captures are taken from the browser.
 - Remote camera control: use the camera panel below the video in the browser to change zoom, focus, white balance and exposure on the device.
 - Pointer and messages: use the pointer button to point at a spot in the video, and send a text message. Both appear on the device screen.
 - Two-way audio (optional): in Kazami's Settings, turn on "Audio Enable". Speaker and microphone buttons then appear. Both start off.

4. Clean up (optional)
 - "ルームを終了" (End room) in the browser deletes the room and the pairing. Guest rooms are deleted automatically 24 hours after last use.

Notes
 - Video and audio go peer-to-peer between the device and the browser, or through a TURN relay when a direct connection is not possible. We do not record or store them.
 - Camera: used to stream the live image to the person viewing the room. Microphone: used only while the microphone button is on. Local network: used when kazayomi runs on the same network.
 - Contact during review: <NAME>, <EMAIL>
```

## 日本語訳（確認用）

Kazami は iPhone や iPad を遠隔の監視カメラにするアプリで、現場のカメラをブラウザで見る Web アプリ kazayomi と組み合わせて使います。アプリにログインはなく、1 回限りの QR を読み取って kazayomi のルームとつなぎます。kazayomi のゲスト機能を使えば、アカウント・メールアドレス・Google ログインなしで、すべての機能を試せます。

1. ブラウザで `<KAZAYOMI_URL>/login` を開き、「ゲストとして試す」にニックネームを入れて同意し、「ゲストとして始める」を押す。一時的なルームが開き、登録 QR が出る
2. Kazami を起動し、右上の歯車（設定）→「QRコードで端末登録」で QR を読む。「完了」→「保存」で自動でつながる
3. ブラウザで、映像・撮像（ブラウザの撮像ボタン。画像はブラウザに直接届く。ゲストのルームはサーバに画像を保存しないので、Kazami 本体の撮像ボタンは出ない）・映像の下のパネルでのカメラの遠隔調整・ポインター・メッセージを試す。音声は Kazami の設定の「Audio Enable」で使える
4. 「ルームを終了」でルームと登録が消える。使わなくても 24 時間で消える

映像と音声は、端末とブラウザのあいだを P2P か TURN の中継で流れ、運営者は記録・保存しない。
