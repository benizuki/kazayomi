<template>
  <v-btn
    :icon="icon"
    variant="text"
    size="small"
    :aria-label="`表示テーマ: ${label}。押すと切り替わります`"
    @click="cycleMode"
  >
    <v-icon :icon="icon" />
    <v-tooltip activator="parent">表示テーマ: {{ label }}</v-tooltip>
  </v-btn>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useThemeMode } from '@/composables/useThemeMode'

const { mode, cycleMode } = useThemeMode()

// 「システムに従う」が既定なので、その状態も見て分かるようにする。
// 太陽/月の 2 択にすると、いま OS に従っているのかが分からなくなる。
const icon = computed(() => ({
  system: 'mdi-theme-light-dark',
  light:  'mdi-weather-sunny',
  dark:   'mdi-weather-night',
}[mode.value]))

const label = computed(() => ({
  system: 'システムに合わせる',
  light:  'ライト',
  dark:   'ダーク',
}[mode.value]))
</script>
