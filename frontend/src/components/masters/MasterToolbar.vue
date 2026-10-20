<template>
  <div class="master-toolbar">
    <v-text-field
      v-model="search"
      prepend-inner-icon="mdi-magnify"
      :placeholder="placeholder"
      density="compact"
      clearable
      class="master-toolbar__search"
    />
    <slot />
    <v-spacer />
    <v-btn v-if="addLabel" color="primary" prepend-icon="mdi-plus" @click="emit('add')">{{ addLabel }}</v-btn>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ modelValue: string; addLabel?: string; placeholder?: string }>(), {
  addLabel: '', placeholder: '絞り込み',
})
const emit = defineEmits<{ 'update:modelValue': [value: string]; add: [] }>()
const search = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v ?? '') })
</script>

<style scoped>
.master-toolbar { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-3); }
.master-toolbar__search { max-width: 320px; }
</style>
