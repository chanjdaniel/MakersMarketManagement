<script setup lang="ts">
  import ElementSettingContainer from '@/components/elements/ElementSettingContainer.vue';
</script>

<template>
    <div class="market-setup-view">
      <div class="market-setup-body">
        <div class="settings-container">
          <div class="settings-header"><h1>Settings</h1></div>
          <div class="settings-body">
            <ElementSettingContainer />
            <ElementSettingContainer />
            <ElementSettingContainer />
            <ElementSettingContainer />
          </div>
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
    display: flex;
    flex-direction: column;
  }

  .settings-header {
    width: 100%;
    height: 50px;
    background-color: var(--mm-black);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .settings-body {
    width: 100%;
    flex-grow: 1;
    display: grid;
    grid-template-columns: auto auto;
    grid-template-rows: auto auto;
    gap: 30px;
    padding: 30px;
  }

  h1 {
    font-family: 'Outfit Regular';
    text-align: center;
    font-size: 30px;
    color: white;
  }

  .done-button {
    margin-left: auto;
    margin-top: 15px;
    width: 100px;
    height: 35px;

    background: var(--mm-green);
    border-radius: 5px;
    border: none;

    font-family: 'Merge One';
    font-style: normal;
    font-weight: 400;
    font-size: 20px;
    line-height: 15px;
    text-align: center;

    color: #FFFFFF;
  }
</style>