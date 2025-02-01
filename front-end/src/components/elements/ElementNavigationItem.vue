<script setup lang="ts"></script>

<template>
    <div class="item">
      <slot name="icon"></slot>
      <slot></slot>
    </div>
</template>

<style scoped>
.item {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 0px;

  width: 100%;
  height: 36px;

  background: #272323;
  box-shadow: 0px 0px 4px 2px rgba(0, 0, 0, 0.25);
  border-radius: 10px;
}

h3 {
  font-size: 1.2rem;
  font-weight: 500;
  margin-bottom: 0.4rem;
  color: var(--color-heading);
}
</style>