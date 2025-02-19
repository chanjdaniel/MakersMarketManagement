<script setup lang="ts"></script>

<template>
    <div class="setting-container">
        <div class="setting-header"></div>
        <div class="setting-body"></div>
    </div>
</template>

<style scoped>
    .setting-container {
        width: 100%;
        height: 100%;

        border-radius: 10px;

        display: flex;
        flex-direction: column;
        
        background-color: white;
        box-shadow: 0px 0px 4px 5px rgba(0, 0, 0, 0.25);
    }

    .setting-header {
        height: 50px;
        background-color: var(--mm-black);
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
    }

    .setting-body {
        flex-grow: 1;
        background-color: white;
        border-bottom-left-radius: 10px;
        border-bottom-right-radius: 10px;
    }
</style>