<template>
  <div class="multi">
    <div class="toolbar">
      <v-select
        v-model="selectedIds"
        :items="roomItems"
        label="表示するルーム"
        multiple
        chips
        closable-chips
        density="compact"
        class="toolbar__rooms"
      />
      <v-btn-toggle v-model="tileSize" mandatory density="compact" divided variant="outlined">
        <v-btn value="s">小</v-btn>
        <v-btn value="m">中</v-btn>
        <v-btn value="l">大</v-btn>
      </v-btn-toggle>
      <v-select v-model="codec" :items="codecItems" label="コーデック" density="compact" class="toolbar__codec" />
      <v-spacer />
      <span class="meta-text">1 つのルームを見られるのは 1 か所だけです（単一ビューと同時には開けません）</span>
    </div>

    <v-alert v-if="error" type="error" class="mx-4">{{ error }}</v-alert>

    <div v-if="config && tiles.length === 0 && !loading" class="empty-state">
      <v-icon icon="mdi-view-grid-outline" size="40" />
      <p>上の「表示するルーム」から、並べるルームを選んでください。</p>
    </div>

    <div v-if="config" class="tiles" :class="{ 'tiles--max': maximizedId }" :style="{ '--tile-min': tileMin }">
      <!-- 最大化しても他のタイルは消さない（つなぎ直しにならないよう v-show で隠す） -->
      <MultiTile
        v-for="room in tiles"
        v-show="!maximizedId || maximizedId === room.id"
        :key="`${room.id}:${codec}`"
        :room="room"
        :config="config"
        :codec="codec"
        :maximized="maximizedId === room.id"
        @maximize="maximizedId = maximizedId === room.id ? null : room.id"
        @open-single="openSingle(room.id)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MultiTile from '@/components/MultiTile.vue'
import { useRooms } from '@/composables/useRooms'
import { useConfig } from '@/composables/useConfig'
import { useStoredRef } from '@/composables/useStoredRef'

const router = useRouter()
const { rooms, loading, error, fetchRooms } = useRooms()
const { config, load: loadConfig } = useConfig()

const selectedIds = useStoredRef<string[]>('kazayomi.multiRooms', [])
const tileSize = useStoredRef<'s' | 'm' | 'l'>('kazayomi.multiTileSize', 'm')
const codec = useStoredRef('kazayomi.codec', '')
const maximizedId = ref<string | null>(null)

const codecItems = [
  { title: '指定なし', value: '' },
  { title: 'H264', value: 'H264' },
  { title: 'VP8', value: 'VP8' },
  { title: 'VP9', value: 'VP9' },
  { title: 'AV1', value: 'AV1' },
]

const roomItems = computed(() => rooms.value.map((c) => ({ title: c.name, value: c.id })))
const tiles = computed(() => rooms.value.filter((c) => selectedIds.value.includes(c.id)))
const tileMin = computed(() => ({ s: '280px', m: '420px', l: '640px' }[tileSize.value]))

watch(tiles, (list) => {
  if (maximizedId.value && !list.some((c) => c.id === maximizedId.value)) maximizedId.value = null
})

function openSingle(roomId: string): void {
  // 同じルームは 1 か所でしか見られないので、タイルを外してから単一ビューへ移る
  selectedIds.value = selectedIds.value.filter((id) => id !== roomId)
  void router.push(`/view/${roomId}`)
}

onMounted(async () => {
  try {
    await loadConfig()
  } catch (e) {
    error.value = (e as Error).message
  }
  await fetchRooms()
  // 削除されたルームが選択に残っていたら外す
  selectedIds.value = selectedIds.value.filter((id) => rooms.value.some((c) => c.id === id))
})
</script>

<style scoped>
.multi { display: flex; flex-direction: column; height: calc(100dvh - var(--app-top)); }
.toolbar { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); flex-wrap: wrap; }
.toolbar__rooms { min-width: 280px; max-width: 640px; }
.toolbar__codec { max-width: 140px; }
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--tile-min), 1fr));
  gap: var(--sp-3);
  align-content: start;
  flex: 1;
  min-height: 0;
  padding: 0 var(--sp-4) var(--sp-4);
  overflow-y: auto;
}
.tiles--max { grid-template-columns: 1fr; grid-template-rows: 1fr; }
</style>
