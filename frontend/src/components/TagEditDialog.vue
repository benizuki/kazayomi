<template>
  <v-dialog v-model="dialog" max-width="480">
    <v-card>
      <v-card-title class="dialog-title">タグを付ける</v-card-title>
      <v-card-text class="form">
        <!-- 取り違えを防ぐため、対象の枚数をそのまま出す -->
        <div>{{ count }} 枚の画像が対象です。</div>
        <v-alert v-if="error" type="error">{{ error }}</v-alert>
        <!-- ボタン同士を離して並べる（くっつけると押し間違えやすい） -->
        <v-btn-toggle v-model="mode" mandatory density="compact" variant="outlined" class="mode-toggle">
          <v-btn value="add">追加</v-btn>
          <v-btn value="replace">置き換え</v-btn>
          <v-btn value="remove">外す</v-btn>
        </v-btn-toggle>
        <p class="meta-text">{{ modeHint }}</p>

        <!-- 表記ゆれを増やさないよう、まず使われているタグから選ばせる -->
        <template v-if="choices.length > 0">
          <div class="meta-text">{{ mode === 'remove' ? '外すタグ' : '使われているタグ' }}</div>
          <div class="tag-chips">
            <v-chip
              v-for="tag in choices"
              :key="tag"
              size="small"
              color="secondary"
              :variant="isPicked(tag) ? 'elevated' : 'outlined'"
              @click="toggle(tag)"
            >#{{ tag }}</v-chip>
          </div>
        </template>
        <p v-else-if="mode === 'remove'" class="meta-text">選んだ画像にタグは付いていません。</p>

        <v-text-field
          v-if="mode !== 'remove'"
          v-model="input"
          label="新しいタグ"
          hint="一覧にないタグは、カンマ区切りで入力します（例: 傷, 要確認）。"
          persistent-hint
          density="compact"
          autofocus
          @keydown.enter.prevent="canApply && save()"
        />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="saving" @click="dialog = false">キャンセル</v-btn>
        <v-btn color="primary" :loading="saving" :disabled="!canApply" @click="save">適用</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
/**
 * 選んだ画像にタグをまとめて付ける・外す。
 * どのタグを、どう当てるかだけを決め、送るのは呼び出し元（onApply）に任せる。
 */
import { computed, ref, watch } from 'vue'
import { MAX_TAGS, splitTags, tagKey, uniqueTags } from '@/composables/tags'
import type { TagMode } from '@/types'

const props = defineProps<{
  modelValue:  boolean
  count:       number
  /** 使われているタグ（多い順） */
  suggestions: string[]
  /** 選んだ画像に付いているタグ。「置き換え」の起点と、「外す」の候補にする */
  currentTags: string[]
  onApply:     (tags: string[], mode: TagMode) => Promise<unknown>
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const dialog = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const mode = ref<TagMode>('add')
/** 選んだタグ（tagKey の形） */
const picked = ref<string[]>([])
const input = ref('')
const saving = ref(false)
const error = ref<string | null>(null)

const modeHint = computed(() => ({
  add:     'いま付いているタグは残したまま、選んだタグを足します。',
  replace: '選んだ画像のタグを、ここで選んだタグだけにします（何も選ばなければタグを全部外します）。',
  remove:  '選んだ画像から、ここで選んだタグを外します。',
}[mode.value]))

/** 外すときは、選んだ画像に付いているタグだけを並べる */
const choices = computed(() =>
  mode.value === 'remove' ? props.currentTags : uniqueTags([...props.currentTags, ...props.suggestions]),
)

const isPicked = (tag: string) => picked.value.includes(tagKey(tag))

function toggle(tag: string): void {
  const key = tagKey(tag)
  picked.value = isPicked(tag) ? picked.value.filter((v) => v !== key) : [...picked.value, key]
}

const resultTags = computed(() => uniqueTags([
  ...choices.value.filter(isPicked),
  ...(mode.value === 'remove' ? [] : splitTags(input.value)),
]))

const canApply = computed(() => {
  if (mode.value === 'replace') return resultTags.value.length <= MAX_TAGS
  return resultTags.value.length > 0
})

// 開くたびに作り直す。前回の入力が残っていると、意図しないタグが付く
watch(() => props.modelValue, (open) => {
  if (!open) return
  mode.value = 'add'
  picked.value = []
  input.value = ''
  error.value = null
})
// 「置き換え」は今の状態から始める（要らないものを外す、という手順になるため）
watch(mode, (next) => {
  picked.value = next === 'replace' ? props.currentTags.map(tagKey) : []
  input.value = ''
})

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    await props.onApply(resultTags.value, mode.value)
    dialog.value = false
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--sp-3); }
.tag-chips { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
/* v-btn-toggle は既定でボタンをつなげて 1 つの枠にするので、離して 1 つずつ角を丸める */
.mode-toggle { gap: var(--sp-2); overflow: visible; border: 0; }
.mode-toggle :deep(.v-btn) {
  border: 1px solid var(--border-default) !important;
  border-radius: var(--radius-sm) !important;
}
.mode-toggle :deep(.v-btn.v-btn--active) { border-color: var(--border-brand) !important; }
</style>
