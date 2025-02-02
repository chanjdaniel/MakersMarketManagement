<script setup lang="ts">
defineProps<{
  loadOpen: boolean;
}>();
</script>

<template>
    <div class="container" :style="{ visibility: loadOpen ? 'visible' : 'hidden' }">
        <div
            class="background"
            @click="$emit('loadClose')"
            :style="{ opacity: loadOpen ? '100%' : '0%' }">
        </div>
        <div class="load-container">
            <div class="file-drop"></div>
            <div class="load-market"></div>
        </div>
    </div>
</template>

<style scoped>
.container {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
}

.background {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    opacity: 0%;
    transition: opacity 0.3s ease-in-out, visibility 0.3s ease-in-out;
}
</style>