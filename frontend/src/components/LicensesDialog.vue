<template>
  <v-dialog v-model="dialog" max-width="480">
    <v-card>
      <v-card-title class="dialog-title">ライセンス</v-card-title>
      <v-card-text class="dialog-body">
        <p>kazayomi は Apache License 2.0 で公開しています。あわせて、次のオープンソースソフトウェアを使っています。</p>
      </v-card-text>
      <!-- ビルド時に dist/licenses/ に書き出したテキスト。backend.txt はコンテナのビルドでだけ作る -->
      <v-list density="compact">
        <v-list-item v-for="item in items" :key="item.href" :href="item.href" target="_blank" rel="noopener"
          prepend-icon="mdi-file-document-outline" :title="item.title" :subtitle="item.subtitle" />
      </v-list>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="dialog = false">閉じる</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const dialog = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const items = [
  { href: '/licenses/LICENSE.txt',  title: 'kazayomi',               subtitle: 'Apache License 2.0' },
  { href: '/licenses/frontend.txt', title: '画面で使っているライブラリ', subtitle: 'Vue、Vuetify、Material Design Icons など' },
  { href: '/licenses/backend.txt',  title: 'サーバで使っているライブラリ', subtitle: 'FastAPI、Pillow、boto3 など' },
]
</script>
