<script setup lang="ts">
import { ref, toRef, onMounted, onUnmounted, watch, nextTick } from 'vue';
import { type SetupObject, type SectionObject } from '@/assets/types/datatypes'
import IconAddRound from '@/components/icons/IconAddRound.vue';
import IconCloseRound from '@/components/icons/IconCloseRound.vue';

const hostname = import.meta.env.VITE_FLASK_HOST;

const props = defineProps<{ setupObject: SetupObject }>();
const emit = defineEmits(["update:setupObject"]);

const updateSetupObject = () => {
    emit("update:setupObject", setupObject.value);
};

const setupObject = toRef(props, "setupObject");
const sections = toRef(setupObject.value, "sections");
const locations = toRef(setupObject.value, "locations");
const tiers = toRef(setupObject.value, "tiers");
const tableCount = ref(0);

const container = ref<HTMLElement | null>(null);
const columnTitles = ref<HTMLElement | null>(null);
const tableCountRef = ref<HTMLElement | null>(null);
const rows = ref<HTMLElement | null>(null);

const rowsMaxHeight = ref<string | null>(null);

const setHeight = () => {
    rowsMaxHeight.value = "0px";
    nextTick(() => {
        if (container.value && columnTitles.value && rows.value) {
            rowsMaxHeight.value = `${container.value.clientHeight - columnTitles.value.clientHeight - 30}px`;
        }
    });
};

const resizeObserver = new ResizeObserver(setHeight);

onMounted(() => {
    setHeight();
    countTables();
    nextTick(() => {
        resizeObserver.observe(document.body);
    })
});

onUnmounted(() => {
    resizeObserver.disconnect();
});

watch(
    () => setupObject.value.sections,
    () => {
        emit("update:setupObject", setupObject.value);
    },
    { deep: true }
);

const hoverIndex = ref<number | null>(null);

const addRow = () => {
    const newSection: SectionObject = {
        name: "",
        location: null,
        tier: null,
        count: "0",
    }
    sections.value.push(newSection);
    updateSetupObject();
    countTables();
    setHeight();
}

const removeRow = (index: number | null) => {
    if (index != null) {
        sections.value.splice(index, 1);
    }
    updateSetupObject();
    countTables();
    setHeight();
}

const countTables = () => {
    let sum = 0;
    for (let i = 0; i < sections.value.length; i++) {
        const count = parseFloat(sections.value[i].count);
        sum += isNaN(count) ? 0 : count;
    }
    tableCount.value = sum;
}
</script>

<template>
    <div class="container" ref="container">
        <div class="column-titles row-container" ref="columnTitles">
            <h3>Section Name</h3>
            <h3>Location</h3>
            <h3>Tier</h3>
            <h3>Count</h3>
        </div>
        <div class="rows" ref="rows">
            <div class="row-container row" v-for="(item, index) in sections" :key="index" @mouseover="hoverIndex = index"
                @mouseleave="hoverIndex = null">
                <div class="row-item">
                    <div class="input-container">
                        <input type="text" v-model="sections[index].name" @blur="updateSetupObject"
                            style="all: unset; font-size: 14px; width: 100%;" />
                    </div>
                </div>
                <div class="row-item">
                    <select class="dropdown" v-model="sections[index].location" @blur="updateSetupObject">
                        <option disabled value="">{{ null }}</option>
                        <option class="display-list" v-for="value in setupObject.locations" :key="value.name"
                            :value="value">
                            {{ value.name }}
                        </option>
                    </select>
                </div>
                <div class="row-item">
                    <select class="dropdown" v-model="sections[index].tier" @blur="updateSetupObject">
                        <option disabled value="">{{ null }}</option>
                        <option class="display-list" v-for="value in setupObject.tiers" :key="value.id" :value="value">
                            {{ value.name }}
                        </option>
                    </select>
                </div>
                <div class="row-item">
                    <div class="input-container">
                        <input type="number" v-model="sections[index].count" @blur="() => { updateSetupObject(); countTables() }"
                            style="all: unset; font-size: 14px; width: 100%; -moz-appearance: textfield;" />
                    </div>
                </div>
                <div
                    style="padding: none; display: flex; flex-direction: row; align-items: center; justify-content: center;">
                    <IconCloseRound :class="{ 'hidden-icon': hoverIndex !== index }" class="icon-close-round"
                        @click="removeRow(index)" />
                </div>
            </div>
            <div class="add-container">
                <IconAddRound class="icon-add-round" @click="addRow" />
            </div>
        </div>
        <div ref="tableCountRef" style="position: absolute; left: 5px; bottom: -10px">
            <h3 style="font-size: 14px;">Total tables: {{ tableCount }}</h3>
        </div>
    </div>
</template>

<style scoped>
.container {
    width: 100%;
    height: 100%;

    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;

    /* gap: 15px; */
}

.column-titles {
    display: grid;
    grid-template-columns: 23.75% 23.75% 23.75% 23.75% 5%;
    margin-bottom: 15px;
}

.rows {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-height: v-bind(rowsMaxHeight);

    align-items: center;

    gap: 8px;
    padding-top: 4px;
    padding-bottom: 8px;

    overflow-y: auto;
    overflow-x: hidden;
}

.row {
    display: grid;
    grid-template-columns: 23.75% 23.75% 23.75% 23.75% 5%;
    padding-top: 5px;
    padding-bottom: 5px;
}

.row-item {
    display: flex;
    flex-direction: row;
    position: relative;

    padding-left: 10px;
    padding-right: 5px;
    justify-content: center;
    align-items: center;

    border-right: 3px solid var(--mm-grey);
}

.row-item:last-of-type {
    border: none;
}

.input-container {
    width: 80%;
    height: 100%;
    box-shadow: inset 0px 0px 4px 2px rgba(0, 0, 0, 0.25);
    border-radius: 8px;
}

input::-webkit-outer-spin-button,
input::-webkit-inner-spin-button {
    -webkit-appearance: none;
    margin: 0;
}

input[type=number] {
    -moz-appearance: textfield;
}

.hidden-icon {
    visibility: hidden;
}

.icon-add-round {
    width: 40px;
    height: 40px;
    cursor: pointer;
}

.icon-close-round {
    max-width: 20px;
    max-height: 20px;
    width: 80%;
    height: 80%;
    cursor: pointer;
}

.dropdown {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    border: none;
    outline: none;
    cursor: pointer;
    font-size: 14px;
    padding-right: 5px;
    background-color: white;
}
</style>