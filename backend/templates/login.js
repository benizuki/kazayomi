// ログイン画面の処理。CSP の script-src 'self' で動かすため、インラインではなくこのファイルで読む。
//
// - ゲスト（利用者）: Google ログインなしで、ニックネームと利用規約への同意だけで一時的なルームを使う
// - 管理者（運営者）: Google でログインする。登録されていないアカウントでも、招待が届いていれば参加できる
(function () {
  const config = document.getElementById('login-config').dataset;
  const clientId = config.clientId || '';
  const oauthConfigError = config.configError || '';
  const loginRedirect = config.redirect || '/';
  const guestEnabled = config.guestEnabled === 'true';
  const termsVersion = config.termsVersion || '';
  const statusEl = document.getElementById('status');
  const $ = function (id) { return document.getElementById(id); };
  const ROLE_LABELS = { owner: 'グループ管理者', editor: '編集者', viewer: '閲覧者' };

  function setStatus(message, kind) {
    statusEl.textContent = message || '';
    statusEl.className = kind ? 'status ' + kind : 'status';
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body)
    });
    const data = await res.json().catch(function () { return {}; });
    return { ok: res.ok, data: data };
  }

  // 参加・ゲストの開始が済むと、サーバーがログインした状態にしてくれるので、そのまま開く
  async function finish(url, body, busyMessage) {
    setStatus(busyMessage);
    const result = await postJson(url, body);
    if (!result.ok) throw new Error(result.data.error || 'うまくいきませんでした。');
    window.location.href = loginRedirect;
  }

  // 招待の一覧。値は textContent で入れる（HTML として解釈させない）
  function showInvitations(info) {
    $('onboarding-email').textContent = info.email || '';
    const list = $('invitations');
    list.replaceChildren();
    (info.invitations || []).forEach(function (invitation) {
      const item = document.createElement('li');
      item.className = 'invitation';
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = invitation.group_name;
      const role = document.createElement('span');
      role.className = 'role';
      role.textContent = (ROLE_LABELS[invitation.role] || invitation.role) + 'として招待されています';
      name.appendChild(role);
      const join = document.createElement('button');
      join.type = 'button';
      join.textContent = '参加する';
      join.addEventListener('click', async function () {
        join.disabled = true;
        try {
          await finish('/auth/onboarding/accept', { invitation_id: invitation.id },
            '「' + invitation.group_name + '」に参加しています...');
        } catch (error) {
          setStatus(error.message, 'error');
          join.disabled = false;
        }
      });
      item.append(name, join);
      list.appendChild(item);
    });
    $('onboarding').hidden = false;
    setStatus('');
  }

  async function handleCredentialResponse(response) {
    const credential = response && response.credential;
    if (!credential) {
      setStatus('Google から認証情報を取得できませんでした。', 'error');
      return;
    }
    $('onboarding').hidden = true;
    setStatus('サインインを確認しています...');
    try {
      const result = await postJson('/auth/google', { credential: credential });
      if (result.ok) {
        window.location.href = loginRedirect;
        return;
      }
      if (result.data.onboarding) {
        showInvitations(result.data.onboarding);
        return;
      }
      throw new Error(result.data.error || 'ログインに失敗しました。');
    } catch (error) {
      setStatus(error.message || 'ログインに失敗しました。', 'error');
    }
  }

  // ── ゲスト ──
  function updateGuestButton() {
    $('guest-start').disabled = !$('guest-nickname').value.trim() || !$('guest-agree').checked;
  }

  function updateResumeButton() {
    $('resume-start').disabled = !$('resume-code').value.trim() || !$('resume-nickname').value.trim();
  }

  function showResume(show) {
    $('guest').hidden = show;
    $('resume').hidden = !show;
    setStatus('');
    $(show ? 'resume-code' : 'guest-nickname').focus();
  }

  if (guestEnabled) {
    $('guest').hidden = false;
    $('resume-open').addEventListener('click', function () { showResume(true); });
    $('resume-back').addEventListener('click', function () { showResume(false); });
    $('resume-code').addEventListener('input', updateResumeButton);
    $('resume-nickname').addEventListener('input', updateResumeButton);
    $('resume').addEventListener('submit', async function (event) {
      event.preventDefault();
      const button = $('resume-start');
      button.disabled = true;
      try {
        await finish('/auth/guest/resume', {
          code: $('resume-code').value,
          nickname: $('resume-nickname').value
        }, 'ルームに戻っています...');
      } catch (error) {
        setStatus(error.message, 'error');
        updateResumeButton();
      }
    });
    $('guest-nickname').addEventListener('input', updateGuestButton);
    $('guest-agree').addEventListener('change', updateGuestButton);
    $('guest').addEventListener('submit', async function (event) {
      event.preventDefault();
      const button = $('guest-start');
      button.disabled = true;
      try {
        await finish('/auth/guest', {
          nickname: $('guest-nickname').value,
          agree: $('guest-agree').checked,
          version: termsVersion
        }, 'ゲストとして始めています...');
      } catch (error) {
        setStatus(error.message, 'error');
        updateGuestButton();
      }
    });
  }

  window.addEventListener('load', function () {
    // 設定不備は黙って失敗させず、画面に理由を出す（ゲストは Google を使わないので、そのまま使える）
    if (oauthConfigError) { setStatus(oauthConfigError, 'error'); return; }
    if (!clientId) { setStatus('GOOGLE_OAUTH_CLIENT_ID が設定されていないため、Google ログインを表示できません。', 'error'); return; }
    if (!window.google || !window.google.accounts || !window.google.accounts.id) {
      setStatus('Google ログインの初期化に失敗しました。ネットワークを確認してください。', 'error');
      return;
    }
    google.accounts.id.initialize({ client_id: clientId, callback: handleCredentialResponse, ux_mode: 'popup', auto_select: false });
    google.accounts.id.renderButton(document.getElementById('google-signin'),
      { type: 'standard', theme: 'outline', size: 'medium', text: 'signin_with', shape: 'pill', width: 240 });
  });
})();
