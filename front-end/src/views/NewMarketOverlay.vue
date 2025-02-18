<script setup lang="ts">
import ElementFileDrop from '@/components/elements/ElementFileDrop.vue';

defineProps<{
  newOpen: boolean;
}>();
</script>

<template>
    <div class="container" :style="{ visibility: newOpen ? 'visible' : 'hidden' }">
        <div
            class="background"
            @click="$emit('newClose')"
            :style="{ opacity: newOpen ? '100%' : '0%' }">
        </div>
        <ElementFileDrop :isOpen="newOpen"></ElementFileDrop>
    </div>
</template>

<style scoped>
h3 {
    display: inline;
}

.container {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: row;
    justify-content: center;
    align-items: center;
}

.background {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    opacity: 0%;
    transition: opacity 0.15s ease-in-out, visibility 0.15s ease-in-out;
    z-index: 0;
}
</style>
