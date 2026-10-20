<template>
  <div class="usage" :class="`usage--${level}`">
    <div class="usage__text">
      <span class="usage__used">{{ formatBytes(usage) }}</span>
      <span class="meta-text">
        <template v-if="quota != null"> / {{ formatBytes(quota) }}（{{ percent }}%）</template>
        <template v-else>（上限なし）</template>
      </span>
    </div>
    <div v-if="quota != null" class="usage__bar" role="meter" :aria-valuenow="usage" aria-valuemin="0" :aria-valuemax="quota"
         :aria-label="`容量 ${formatBytes(usage)} / ${formatBytes(quota)}`">
      <div class="usage__fill" :style="{ width: `${Math.min(100, percent)}%` }" />
    </div>
  </div>
</template>

<script setup lang="ts">
/** グループの画像の置き場（rustfs）の使用量。上限があれば、どれだけ使っているかを帯で見せる。 */
import { computed } from 'vue'
import { formatBytes } from '@/composables/format'

const props = defineProps<{ usage: number; quota: number | null }>()

const percent = computed(() => (props.quota ? Math.round((props.usage / props.quota) * 100) : 0))
// 8 割を超えたら注意、上限に達したら（もう保存できない）警告の色にする
const level = computed(() => (props.quota == null ? 'none' : percent.value >= 100 ? 'full' : percent.value >= 80 ? 'warn' : 'ok'))
</script>

<style scoped>
.usage { display: flex; flex-direction: column; gap: 4px; min-width: 160px; }
.usage__text { display: flex; align-items: baseline; gap: 2px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.usage__used { color: var(--ink-1); }
.usage__bar { height: 6px; border-radius: var(--radius-pill); background: var(--surface-subtle); overflow: hidden; }
.usage__fill { height: 100%; border-radius: inherit; background: var(--text-brand); transition: width 0.3s ease; }
.usage--warn .usage__fill { background: var(--text-warn); }
.usage--full .usage__fill { background: var(--text-danger); }
.usage--full .usage__used { color: var(--text-danger); }
</style>
