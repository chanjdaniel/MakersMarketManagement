<script setup lang="ts">

</script>

<template>
    <div class="market-setup-view">
      <div class="market-setup-body">
        <div class="settings-container">
          <div class="settings-header"><h1>Settings</h1></div>
          <div class="settings-body"></div>
        </div>
        <button class="done-button">Done</button>
      </div>
    </div>
</template>

<style scoped>
  .market-setup-view {
    width: 100%;
    height: 100%;

    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }

  .market-setup-body {
    width: 80%;
    height: 100%;

    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }

  .settings-container {
    width: 100%;
    height: 80%;
    background-color: white;
    box-shadow: 0px 0px 4px 5px rgba(0, 0, 0, 0.25);
  }

  .settings-header {
    width: 100%;
    height: 6%;
    background-color: var(--mm-black);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  h1 {
    font-family: 'Outfit Regular';
    text-align: center;
    font-size: 30px;
    color: white;
  }

  .done-button {
    margin-left: auto;
  }
</style>