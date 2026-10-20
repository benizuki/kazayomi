<template>
  <v-dialog v-model="dialog" max-width="440">
    <v-card>
      <v-card-title class="dialog-title">{{ title }}</v-card-title>
      <v-card-text class="dialog-body">
        <slot>{{ message }}</slot>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="dialog = false">キャンセル</v-btn>
        <v-btn :color="danger ? 'error' : 'primary'" :loading="busy" @click="emit('confirm')">{{ confirmText }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue:   boolean
  title:        string
  message?:     string
  confirmText?: string
  danger?:      boolean
  busy?:        boolean
}>(), { message: '', confirmText: 'OK', danger: false, busy: false })

const emit = defineEmits<{ 'update:modelValue': [value: boolean]; confirm: [] }>()

const dialog = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
</script>
