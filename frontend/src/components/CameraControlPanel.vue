<template>
  <div class="panel side__block camera">
    <!-- いつも使うものではないので、たたんでおける（開いているかは覚えておく） -->
    <button type="button" class="camera__head" :aria-expanded="open" @click="open = !open">
      <v-icon icon="mdi-camera-control" size="18" />
      <span class="field-label camera__title">カメラの調整</span>
      <span v-if="state?.camera" class="meta-text camera__name">{{ state.camera }}</span>
      <v-spacer v-else />
      <v-icon :icon="open ? 'mdi-chevron-up' : 'mdi-chevron-down'" size="18" />
    </button>

    <template v-if="!open" />
    <p v-else-if="!connection.controlOpen.value" class="meta-text">つながると、Kazami のカメラを遠隔で調整できます。</p>
    <p v-else-if="!supported" class="tip tip--compact tip--warn">
      <v-icon icon="mdi-alert-outline" />
      <span>この Kazami は遠隔の調整に対応していません。Kazami を新しい版にしてください。</span>
    </p>
    <p v-else-if="!state" class="meta-text">カメラの設定を読み込んでいます…</p>
    <p v-else-if="!state.adjustable" class="meta-text">このカメラは調整できません（シミュレータのテスト映像など）。</p>

    <template v-else>
      <!-- 倍率 -->
      <div class="control">
        <div class="control__label">
          <span>倍率</span>
          <span class="control__value">{{ zoom.toFixed(1) }}×</span>
        </div>
        <div class="control__presets">
          <v-btn
            v-for="preset in state.zoomPresets"
            :key="preset"
            size="small"
            :variant="Math.abs(zoom - preset) < 0.05 ? 'flat' : 'outlined'"
            :color="Math.abs(zoom - preset) < 0.05 ? 'secondary' : undefined"
            @click="setZoom(preset)"
          >{{ preset }}×</v-btn>
        </div>
        <v-slider
          v-if="state.maxZoom > 1"
          :model-value="zoom"
          :min="1"
          :max="state.maxZoom"
          :step="0.1"
          hide-details
          color="secondary"
          @update:model-value="setZoom"
        />
      </div>

      <!-- フォーカス -->
      <div class="control">
        <div class="control__label">
          <span>フォーカス</span>
          <span class="control__value">{{ focus == null ? 'オート' : `${Math.round(focus * 100)}` }}</span>
        </div>
        <div class="control__row">
          <v-btn size="small" :variant="focus == null ? 'flat' : 'outlined'" :color="focus == null ? 'secondary' : undefined" @click="setFocus('auto')">オート</v-btn>
          <v-slider
            :model-value="focus ?? 0.5"
            :min="0"
            :max="1"
            :step="0.01"
            :disabled="!state.manualFocus"
            hide-details
            color="secondary"
            class="control__slider"
            @update:model-value="setFocus"
          >
            <template #prepend><span class="control__end">近</span></template>
            <template #append><span class="control__end">遠</span></template>
          </v-slider>
        </div>
        <p class="meta-text">映像をダブルクリックすると、その位置にフォーカスと露出を合わせます。</p>
      </div>

      <!-- 色合い（ホワイトバランス） -->
      <div class="control">
        <div class="control__label">
          <span>色合い</span>
          <span class="control__value">{{ whiteBalance == null ? 'オート' : `${Math.round(whiteBalance)}K` }}</span>
        </div>
        <div class="control__row">
          <v-btn size="small" :variant="whiteBalance == null ? 'flat' : 'outlined'" :color="whiteBalance == null ? 'secondary' : undefined" @click="setWhiteBalance('auto')">オート</v-btn>
          <v-slider
            :model-value="whiteBalance ?? 5000"
            :min="state.whiteBalanceRange[0]"
            :max="state.whiteBalanceRange[1]"
            :step="100"
            :disabled="!state.manualWhiteBalance"
            hide-details
            color="secondary"
            class="control__slider control__slider--wb"
            @update:model-value="setWhiteBalance"
          >
            <template #prepend><span class="control__end">青</span></template>
            <template #append><span class="control__end">赤</span></template>
          </v-slider>
        </div>
      </div>

      <!-- 露出 -->
      <div class="control">
        <div class="control__label">
          <span>露出</span>
          <span class="control__value">{{ exposure > 0 ? '+' : '' }}{{ exposure.toFixed(1) }} EV</span>
        </div>
        <div class="control__row">
          <v-btn size="small" :variant="Math.abs(exposure) < 0.05 ? 'flat' : 'outlined'" :color="Math.abs(exposure) < 0.05 ? 'secondary' : undefined" @click="setExposure(0)">±0</v-btn>
          <v-slider
            :model-value="exposure"
            :min="state.exposureRange[0]"
            :max="state.exposureRange[1]"
            :step="0.1"
            hide-details
            color="secondary"
            class="control__slider"
            @update:model-value="setExposure"
          >
            <template #prepend><span class="control__end">暗</span></template>
            <template #append><span class="control__end">明</span></template>
          </v-slider>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * Kazami のカメラ（倍率・フォーカス・色合い・露出）を DataChannel で遠隔から変える。
 *
 * - つながったら cameraGet で今の設定を聞き、cameraState で返ってきた値を表示する
 * - スライダーを動かしている間は手元の値をすぐ変え、Kazami へは間引いて送る（送りすぎると詰まる）
 * - Kazami の画面で変えたときも cameraState が届くので、表示がそろう
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AyameConnection } from '@/composables/useAyameConnection'
import { useStoredRef } from '@/composables/useStoredRef'
import type { CameraSettings, CameraState } from '@/types'

const props = defineProps<{ connection: AyameConnection }>()

const open = useStoredRef('kazayomi.cameraPanelOpen', false)
const state = ref<CameraState | null>(null)
// 表示する値。送った直後は Kazami からの返事を待たずに変える（スライダーが戻って見えないように）
const zoom = ref(1)
const focus = ref<number | null>(null)
const whiteBalance = ref<number | null>(null)
const exposure = ref(0)

const supported = computed(() => props.connection.peerInfo.value?.capabilities?.includes('camera') ?? false)

// 送った値が Kazami に届いて返ってくるまでは、古い cameraState で表示を戻さない
let pendingUntil = 0

function apply(next: CameraState): void {
  state.value = next
  if (Date.now() < pendingUntil) return
  zoom.value = next.zoom
  focus.value = next.focus
  whiteBalance.value = next.whiteBalance
  exposure.value = next.exposure
}

const stopListening = props.connection.onControlMessage((message) => {
  if (message.type === 'cameraState') {
    const { type: _type, ...next } = message
    apply(next)
  }
})

watch(
  () => props.connection.controlOpen.value && supported.value,
  (ready) => {
    if (ready) props.connection.sendControl({ type: 'cameraGet' })
    else state.value = null
  },
  { immediate: true },
)

// ── 送る（間引く） ────────────────────────────────
const SEND_INTERVAL_MS = 120
let pending: CameraSettings = {}
let timer: number | undefined

function queue(change: CameraSettings): void {
  pending = { ...pending, ...change }
  pendingUntil = Date.now() + 800
  if (timer !== undefined) return
  timer = window.setTimeout(flush, SEND_INTERVAL_MS)
}

function flush(): void {
  timer = undefined
  const message = pending
  pending = {}
  if (Object.keys(message).length > 0) props.connection.sendControl({ type: 'cameraSet', ...message })
}

function setZoom(value: number): void {
  zoom.value = value
  queue({ zoom: value })
}

function setFocus(value: number | 'auto'): void {
  focus.value = value === 'auto' ? null : value
  queue({ focus: value })
}

function setWhiteBalance(value: number | 'auto'): void {
  whiteBalance.value = value === 'auto' ? null : value
  queue({ whiteBalance: value })
}

function setExposure(value: number): void {
  exposure.value = value
  queue({ exposure: value })
}

onBeforeUnmount(() => {
  stopListening()
  window.clearTimeout(timer)
})
</script>

<style scoped>
.camera { display: flex; flex-direction: column; gap: var(--sp-3); }
.camera__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ink-3);
  text-align: left;
  cursor: pointer;
}
.camera__head:hover .field-label { color: var(--ink-1); }
.camera__title { flex: none; white-space: nowrap; }
/* カメラの名前は長いことがあるので、はみ出す分は省く */
.camera__name { flex: 1; min-width: 0; overflow: hidden; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.control { display: flex; flex-direction: column; gap: var(--sp-1); }
.control__label { display: flex; justify-content: space-between; color: var(--ink-2); font-size: var(--fs-sm); }
.control__value { color: var(--ink-3); font-variant-numeric: tabular-nums; }
.control__presets { display: flex; flex-wrap: wrap; gap: var(--sp-1); }
.control__row { display: flex; align-items: center; gap: var(--sp-2); }
.control__slider { flex: 1; min-width: 0; }
.control__end { color: var(--ink-4); font-size: var(--fs-xs); }
/* 指定する色温度は「照明の色」。低くすると青みに、高くすると赤みに写る（iOS の標準カメラと同じ向き） */
.control__slider--wb :deep(.v-slider-track__background) {
  background: linear-gradient(to right, #7aa7e0, #f3efe6, #e8a25a) !important;
  opacity: 1 !important;
}
</style>
