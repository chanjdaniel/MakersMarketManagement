<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
// @ts-ignore
import ElementBanner from './components/elements/ElementBanner.vue'
import ElementNavigation from './components/elements/ElementNavigation.vue';

import { useElementSize } from '@vueuse/core';
import { onMounted, ref, useTemplateRef, watch } from 'vue';

const navOpen = ref(false);
</script>

<script>

</script>

<template>

  <header>
    <ElementBanner @menuOpen="navOpen = true"/>
  </header>

  <RouterView />

  <div
    class="nav-background"
    :style="{
      opacity: navOpen ? '100%' : '0%', 
      visibility: navOpen ? 'visible' : 'hidden'
    }"
    @click="navOpen = false">
  </div>
  
  <ElementNavigation
    class="nav-bar"
    :style="{ left: navOpen ? '0px' : '-300px' }"
    @menuClose="navOpen = false"/>
</template>

<style scoped>
header {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  line-height: 1.5;
  max-height: 100vh;
}

.logo {
  display: block;
  margin: 0 auto 2rem;
}

.nav-bar {
  position: fixed;
  top: 0;
  left: -300px;
  transition: left 0.3s ease-in-out;
}

.nav-bar.nav-open {
  left: 0;
}

.nav-background {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  opacity: 40%;
  transition: opacity 0.3s ease-in-out, visibility 0.3s ease-in-out;
}
</style>
