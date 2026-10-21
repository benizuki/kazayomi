<template>
  <!-- 送ったメッセージ。Kazami の画面に出ているあいだ、映像の右下にも並べる -->
  <TransitionGroup tag="ol" name="chat-sent" class="chat-sent" aria-label="送ったメッセージ">
    <li v-for="message in messages" :key="message.id" class="chat-sent__item">
      <span class="chat-sent__meta">
        <span v-if="message.read">既読</span>
        <span>{{ formatTime(message.sentAt) }}</span>
      </span>
      <span class="chat-sent__bubble">{{ message.text }}</span>
    </li>
  </TransitionGroup>
</template>

<script setup lang="ts">
import type { SentChat } from '@/composables/useChat'

defineProps<{ messages: SentChat[] }>()

function formatTime(date: Date): string {
  return date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.chat-sent {
  position: absolute;
  right: var(--sp-3);
  bottom: var(--sp-3);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--sp-2);
  max-width: min(60%, 420px);
  margin: 0;
  padding: 0;
  list-style: none;
  pointer-events: none;
}
.chat-sent__item { display: flex; align-items: flex-end; gap: 6px; }
.chat-sent__meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  color: #fff;
  font-size: var(--fs-xs);
  line-height: 1.3;
  text-shadow: 0 0 3px rgba(0, 0, 0, 0.9);
  white-space: nowrap;
}
/* LINE の自分の吹き出しのような緑 */
.chat-sent__bubble {
  padding: 8px 12px;
  border-radius: 16px 16px 4px 16px;
  background: #06c755;
  color: #fff;
  font-size: var(--fs-sm);
  line-height: 1.5;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}
.chat-sent-enter-active, .chat-sent-leave-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.chat-sent-enter-from { opacity: 0; transform: translateY(8px); }
.chat-sent-leave-to { opacity: 0; }
</style>
