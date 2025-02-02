<script setup lang="ts">
  import ElementInitButton from '@/components/elements/ElementInitButton.vue';
  import LoadMarketOverlay from './LoadMarketOverlay.vue';
  import { ref } from 'vue';

  const loadOpen = ref(false);
  const newOpen = ref(false);
</script>

<template>
    <div class="init-view">
      <ElementInitButton>
        <h3>
          <span>Set Up </span>
          <span class="text-new">New </span>
          <span>Market</span>
        </h3>
        <template #icon>
          <img alt="Settings" class="nav-icon" src="@/assets/add-square-icon.svg"/>
        </template>
      </ElementInitButton>

      <ElementInitButton @click="loadOpen = true">
        <h3>
          <span>Load </span>
          <span class="text-existing">Existing </span>
          <span>Market</span>
        </h3>
        <template #icon>
          <img alt="Settings" class="nav-icon" src="@/assets/upload-icon.svg"/>
        </template>
      </ElementInitButton>

      <LoadMarketOverlay @loadClose="loadOpen = false" :loadOpen="loadOpen"/>
    </div>
</template>

<style scoped>
.init-view {
  flex-grow: 1;
  display: flex;
  flex-direction: row;

  justify-content: center;
  align-items: center;

  gap: 72px;
  height: 100%;
  width: 100%;
  margin: 0;
}

h3 {
font-family: 'Merge One';
font-style: normal;
font-weight: 100;
font-size: 20px;

color: #ffffff;
}

.text-new {
  color: #49B096;
}

.text-existing {
  color: #E4A629;
}
</style>