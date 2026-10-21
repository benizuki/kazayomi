<template>
  <!-- Kazami の画面に吹き出しで出す。騒がしい現場で声が届かないとき向け -->
  <form class="chat-input" @submit.prevent="submit">
    <v-text-field
      v-model="chat.draft.value"
      :disabled="!chat.available.value"
      :placeholder="chat.unavailableReason.value ?? 'Kazami の画面に文字で伝える（Enter で送る）'"
      :maxlength="CHAT_MAX_LENGTH"
      density="compact"
      variant="outlined"
      hide-details
      autocomplete="off"
      aria-label="Kazami に送るメッセージ"
      prepend-inner-icon="mdi-message-text-outline"
      @keydown.enter="onEnter"
    />
    <v-btn
      icon
      size="small"
      color="primary"
      type="submit"
      :disabled="!chat.available.value || !chat.draft.value.trim()"
      aria-label="送る"
    >
      <v-icon icon="mdi-send" />
      <v-tooltip activator="parent" location="top">送る</v-tooltip>
    </v-btn>
  </form>
</template>

<script setup lang="ts">
import { CHAT_MAX_LENGTH, type useChat } from '@/composables/useChat'

const props = defineProps<{ chat: ReturnType<typeof useChat> }>()

function submit(): void {
  props.chat.send()
}

/** 日本語の変換を確定する Enter では送らない */
function onEnter(event: KeyboardEvent): void {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submit()
}
</script>

<style scoped>
.chat-input { display: flex; align-items: center; gap: var(--sp-2); }
</style>
