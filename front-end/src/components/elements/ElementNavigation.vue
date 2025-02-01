<script setup lang="ts">
    import ElementNavigationItem from './ElementNavigationItem.vue';
</script>

<template>
    <div class="nav-bar">
        <button class="close-button" @click="$emit('menuClose')">
            <img alt="Close button" class="close-icon" src="@/assets/close_round.svg"/>
        </button>

        <div class="nav">
            <ElementNavigationItem>
                <template #icon>
                    <img alt="Settings" class="nav-icon" src="@/assets/settings-icon.svg"/>
                </template>
                <h3>Manage Tables</h3>
            </ElementNavigationItem>

            <ElementNavigationItem>
                <template #icon>
                    <img alt="Vendors" class="nav-icon" src="@/assets/vendors-icon.svg"/>
                </template>
                <h3>
                    <span>View </span>
                    <span class="vendors-1">Vendors</span>
                </h3>
            </ElementNavigationItem>

            <ElementNavigationItem>
                <template #icon>
                    <img alt="Tables" class="nav-icon" src="@/assets/tables-icon.svg"/>
                </template>
                <h3>
                    <span>View </span>
                    <span class="tables-1">Tables</span>
                </h3>
            </ElementNavigationItem>

            <ElementNavigationItem>
                <template #icon>
                    <img alt="Discord" class="nav-icon" src="@/assets/tools-icon.svg"/>
                </template>
                <h3>Discord Tools</h3>
            </ElementNavigationItem>

            <ElementNavigationItem>
                <template #icon>
                    <img alt="Change Log" class="nav-icon" src="@/assets/log-icon.svg"/>
                </template>
                <h3>View Change Log</h3>
            </ElementNavigationItem>

        </div>
    </div>
</template>

<style scoped>
h3 {

font-family: 'Merge One';
font-style: normal;
font-size: 16px;

color: #ffffff;
}

.nav-bar {
    /* Auto layout */
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 10px;

    width: 12%;
    height: 100%;

    min-width: 200px;
    max-width: 300px;

    background: #ffffff;
    border-radius: 0px 10px 10px 0px;
}

.close-button {
    position: absolute;
    top: 0;
    right: 0;
    margin: 5px;
    padding: 0;

    height: 30px;
    aspect-ratio: 1;

    display: flex;
    align-items: center;
    justify-content: center;

    cursor: pointer;
    background-color: transparent;
    border: none;
}

.close-icon {
    aspect-ratio: 1;
    background-color: none;
}

.nav {
display: flex;
flex-direction: column;
position: relative;
top: 30px;
width: 100%;
gap: 10px;
}

.vendors-1 {
    color: #49B096;
}

.tables-1 {
    color: #E4A629;
}

.nav-icon {
    height: 24px;
    aspect-ratio: 1;
    margin: 6px;
}


</style>