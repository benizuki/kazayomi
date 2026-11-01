<template>
  <v-dialog v-model="dialog" :max-width="selected ? 760 : 480" scrollable>
    <v-card>
      <v-card-title class="dialog-title licenses-title">
        <v-btn v-if="selected" icon="mdi-arrow-left" variant="text" size="small" aria-label="一覧に戻る" @click="selected = null" />
        <span>{{ selected ? selected.title : 'ライセンス' }}</span>
      </v-card-title>

      <!-- 選んだライセンス文。ビルド時に dist/licenses/ に書き出したテキストを読む -->
      <v-card-text v-if="selected" class="dialog-body">
        <v-progress-linear v-if="loading" indeterminate color="primary" />
        <v-alert v-else-if="error" type="warning" variant="tonal" density="compact">{{ error }}</v-alert>
        <pre v-else class="license-text">{{ text }}</pre>
      </v-card-text>

      <template v-else>
        <v-card-text class="dialog-body">
          <p>kazayomi は Apache License 2.0 で公開しています。あわせて、次のオープンソースソフトウェアを使っています。</p>
        </v-card-text>
        <v-list density="compact">
          <v-list-item v-for="item in items" :key="item.href" prepend-icon="mdi-file-document-outline"
            append-icon="mdi-chevron-right" :title="item.title" :subtitle="item.subtitle" @click="open(item)" />
        </v-list>
      </template>

      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="dialog = false">閉じる</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'

type Item = { href: string; title: string; subtitle: string }

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const dialog = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// backend.txt はコンテナのビルドでだけ作る
const items: Item[] = [
  { href: '/licenses/LICENSE.txt',  title: 'kazayomi',               subtitle: 'Apache License 2.0' },
  { href: '/licenses/frontend.txt', title: '画面で使っているライブラリ', subtitle: 'Vue、Vuetify、Material Design Icons など' },
  { href: '/licenses/backend.txt',  title: 'サーバで使っているライブラリ', subtitle: 'FastAPI、Pillow、boto3 など' },
]

// ref だと中身が Proxy になり、下の selected.value === item が成り立たないので shallowRef にする
const selected = shallowRef<Item | null>(null)
const text = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function open(item: Item): Promise<void> {
  selected.value = item
  text.value = ''
  error.value = null
  loading.value = true
  try {
    const res = await fetch(item.href)
    // ファイルがないと SPA の画面（HTML）が返るので、種類でも確かめる
    if (!res.ok || !res.headers.get('content-type')?.startsWith('text/plain')) {
      throw new Error('ライセンス文が見つかりません。コンテナでビルドしたときだけ同梱されるファイルがあります。')
    }
    const body = await res.text()
    if (selected.value === item) text.value = body
  } catch (e) {
    if (selected.value === item) error.value = (e as Error).message
  } finally {
    if (selected.value === item) loading.value = false
  }
}

// 閉じたら一覧に戻しておく
watch(dialog, (v) => { if (!v) selected.value = null })
</script>

<style scoped>
.licenses-title { display: flex; align-items: center; gap: var(--sp-1); }
.license-text {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
