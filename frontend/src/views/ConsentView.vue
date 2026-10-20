<template>
  <div class="consent">
    <section class="panel consent__card" aria-labelledby="consent-title">
      <h1 id="consent-title" class="page-title">はじめに</h1>
      <p>kazayomi は、カメラアプリ Kazami の映像をブラウザで見るための、試用を目的とした無料のサービスです。</p>
      <ul class="consent__points">
        <li>ゲストには、あなた専用の一時的なルームが 1 つできます。使わないまま 24 時間たつか、終了すると消えます。</li>
        <li>映像・音声・撮像した画像は、ブラウザと Kazami の間で直接やり取りされ、サーバには保存されません。</li>
        <li>ニックネームはこのブラウザにだけ持ち、サーバには保存しません。</li>
        <li>カメラに映る人の同意を得るのは、利用者の責任です。人をこっそり映す使い方はできません。</li>
        <li>動作の保証やサポートはありません。予告なく止めることがあります。</li>
      </ul>
      <p>
        詳しくは <a href="/terms" target="_blank" rel="noopener">利用規約</a> と
        <a href="/privacy" target="_blank" rel="noopener">プライバシーポリシー</a> をお読みください。
      </p>
      <v-checkbox v-model="agreed" hide-details label="利用規約とプライバシーポリシーに同意します" />
      <v-alert v-if="error" type="error" class="mt-2">{{ error }}</v-alert>
      <div class="consent__actions">
        <v-btn variant="text" @click="logout">ログアウト</v-btn>
        <v-btn color="primary" :disabled="!agreed" :loading="saving" @click="accept">同意して始める</v-btn>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
/** ゲストに、はじめに利用規約とプライバシーポリシーへの同意をもらう（規約を改めたら、もう一度）。 */
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { acceptTerms } from '@/composables/useGuestRoom'

const { me, fetchMe, logout } = useAuth()
const agreed = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

async function accept(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    await acceptTerms(me.value?.consent?.version ?? '')
    await fetchMe()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.consent { display: grid; place-items: start center; padding: var(--sp-6) var(--sp-4); }
.consent__card { width: min(100%, 640px); display: flex; flex-direction: column; gap: var(--sp-3); line-height: 1.8; }
.consent__card p { margin: 0; }
.consent__points { margin: 0; padding-left: 1.3em; color: var(--ink-2); }
.consent__actions { display: flex; justify-content: flex-end; gap: var(--sp-2); }
.consent a { color: var(--text-brand); }
</style>
