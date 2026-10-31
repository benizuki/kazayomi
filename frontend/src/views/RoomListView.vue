<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">ルーム</h1>
        <p class="page-lead">見られるルーム（Kazami のルーム）です。カードを開くと映像につながります。</p>
      </div>
    </header>

    <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

    <div v-if="!loading && rooms.length === 0" class="empty-state">
      <v-icon icon="mdi-cctv" size="40" />
      <p v-if="permissions.can_manage_devices">ルームがまだありません。マスター › ルーム で Kazami のルームを登録してください。</p>
      <p v-else>見られるルームがありません。所属グループを管理者に確認してください。</p>
    </div>

    <section v-for="section in sections" :key="section.groupId" class="section">
      <h2 v-if="sections.length > 1" class="section-title section__title">{{ section.groupName }}</h2>
      <div class="grid">
        <v-card v-for="room in section.rooms" :key="room.id" class="room-card" :to="`/view/${room.id}`">
          <div class="room-card__visual">
            <img :src="deviceImage" alt="" class="room-card__image" draggable="false">
          </div>
          <div class="room-card__body">
            <div class="room-card__title">{{ room.name }}</div>
            <div class="meta-text">ルームID: {{ room.ayame_room_id }}</div>
            <div class="meta-text">{{ room.server_name || '既定のサーバ' }}</div>
            <div v-if="room.note" class="room-card__note">{{ room.note }}</div>
          </div>
        </v-card>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
// ルームのカードの絵（Kazami のカメラ）。Vite が同じ Origin の URL にする
import deviceImage from '@/assets/kazami-device.svg'
import { useAuth } from '@/composables/useAuth'
import { useRooms } from '@/composables/useRooms'

const { rooms, loading, error, fetchRooms } = useRooms()
const { permissions } = useAuth()

// 複数のグループを見られる人には、グループごとに分けて並べる
const sections = computed(() => {
  const map = new Map<string, { groupId: string; groupName: string; rooms: typeof rooms.value }>()
  for (const room of rooms.value) {
    const section = map.get(room.group_id) ?? { groupId: room.group_id, groupName: room.group_name, rooms: [] }
    section.rooms.push(room)
    map.set(room.group_id, section)
  }
  return [...map.values()]
})

onMounted(fetchRooms)
</script>

<style scoped>
.section + .section { margin-top: var(--sp-6); }
.section__title { margin-bottom: var(--sp-3); }
.grid {
  display: grid;
  /* 画面が狭いときは、はみ出さずに画面の幅に合わせる */
  grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr));
  gap: var(--sp-5);
}
.room-card { display: flex; flex-direction: column; overflow: hidden; }
.room-card__visual {
  aspect-ratio: 9 / 5;
  overflow: hidden;
  background: #dcdedf;
}
.room-card__image { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform 0.2s; }
.room-card:hover .room-card__image { transform: scale(1.03); }
.room-card__body { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-3) var(--sp-4) var(--sp-4); }
.room-card__title { color: var(--ink-1); font-size: var(--fs-lg, var(--fs-md)); font-weight: var(--fw-bold); }
.room-card__note { color: var(--ink-3); font-size: var(--fs-sm); white-space: pre-wrap; }
</style>
