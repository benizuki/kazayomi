<template>
  <div class="settings">
    <v-alert v-if="error" type="error" closable class="mb-3" @click:close="error = null">{{ error }}</v-alert>

    <section class="panel setting" aria-labelledby="quota-title">
      <div class="setting__text">
        <h2 id="quota-title" class="section-title">新しいグループの容量</h2>
        <p class="meta-text">
          このあとマスター › グループで追加するグループに付ける、画像の置き場の容量の上限です。
          今あるグループの上限は変わりません（グループごとに、マスター › グループで変えます）。
        </p>
      </div>
      <div class="setting__quota">
        <v-text-field v-model="quotaMb" label="容量の上限（MB）" type="number" min="0" step="10" placeholder="空なら無制限" density="compact" hide-details />
        <v-btn color="primary" :loading="saving" :disabled="!settings || quotaMb === toMb(settings.default_group_quota_bytes)" @click="saveQuota">保存</v-btn>
      </div>
    </section>

    <v-snackbar v-model="snackbar" timeout="2000">保存しました</v-snackbar>
  </div>
</template>

<script setup lang="ts">
/** アプリ全体の設定（アプリの管理者だけ）。環境変数ではなく、ここで変える。 */
import { onMounted, ref } from 'vue'
import { toBytes, toMb } from '@/composables/quota'
import { fetchAppSettings, saveAppSettings } from '@/composables/useMasters'
import type { AppSettings } from '@/types'

const settings = ref<AppSettings | null>(null)
const quotaMb = ref('')
const saving = ref(false)
const error = ref<string | null>(null)
const snackbar = ref(false)

async function save(change: Partial<AppSettings>): Promise<void> {
  if (!settings.value) return
  saving.value = true
  error.value = null
  try {
    settings.value = await saveAppSettings({ ...settings.value, ...change })
    quotaMb.value = toMb(settings.value.default_group_quota_bytes)
    snackbar.value = true
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

async function saveQuota(): Promise<void> {
  try {
    await save({ default_group_quota_bytes: toBytes(quotaMb.value) })
  } catch (e) {
    error.value = (e as Error).message
  }
}

onMounted(async () => {
  try {
    settings.value = await fetchAppSettings()
    quotaMb.value = toMb(settings.value.default_group_quota_bytes)
  } catch (e) {
    error.value = (e as Error).message
  }
})
</script>

<style scoped>
.settings { display: flex; flex-direction: column; gap: var(--sp-4); max-width: 860px; }
.setting { display: flex; align-items: center; gap: var(--sp-6); }
.setting__text { flex: 1; min-width: 0; }
.setting__text p { margin: var(--sp-1) 0 0; line-height: 1.8; }
.setting__text a { color: var(--text-brand); }
.section-title { margin: 0; }
.setting__quota { display: flex; align-items: center; gap: var(--sp-2); width: 260px; }
@media (max-width: 720px) {
  .setting { flex-direction: column; align-items: stretch; gap: var(--sp-3); }
  .setting__quota { width: auto; }
}
</style>
