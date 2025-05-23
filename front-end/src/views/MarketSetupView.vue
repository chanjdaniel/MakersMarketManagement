<script setup lang="ts">
import { onMounted, reactive, nextTick, ref } from 'vue';
import { useRouter } from 'vue-router';

import ElementSettingContainer from '@/components/elements/ElementSettingContainer.vue';
import ElementSetupColumns from '@/components/elements/ElementSetupColumns.vue';
import ElementMarketDates from '@/components/elements/ElementMarketDates.vue';
import ElementAssignmentPriority from '@/components/elements/ElementAssignmentPriority.vue';
import ElementTierSetup from '@/components/elements/ElementTierSetup.vue';
import ElementLocationSetup from '@/components/elements/ElementLocationSetup.vue';
import ElementSectionSetup from '@/components/elements/ElementSectionSetup.vue';
import { type SetupObject } from '@/assets/types/datatypes';

const hostname = import.meta.env.VITE_FLASK_HOST;
const router = useRouter();

const settingsBodyHeight = ref(null);

const setupObject = reactive<SetupObject>({
    colNames: [],
    colValues: [],
    colInclude: [],
    enumPriorityOrder: [],
    priority: [],
    marketDates: [],
    tiers: [],
    locations: [],
    sections: [],
});

const pageIdx = ref(0);
const maxPageIdx = 2;

const saveMarket = async () => {
    const response = await fetch(`${hostname}/save-market`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
            market: {
                name: "spring2025",
                owner: "testemail@test.com",
                editors: ["testemail@test.com"],
                viewers: ["testemail@test.com"],
                setupObject: setupObject,
                modificationList: [],
                assignmentObject: null
            },
        }),
    });

    const data = await response.json();
    if (!response.ok) {
        console.log(data);
    }
};

const loadMarket = async () => {
    const response = await fetch(`${hostname}/save-market`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
            name: "spring2025",
        }),
    });

    const data = await response.json();
    if (!response.ok) {
        console.log(data);
    } else {
        localStorage.setItem("market", JSON.stringify(data.market));
        router.push("/market-setup");
    }
};

onMounted(() => {
    // create setup object

    const setupObjectJSON: string | null = localStorage.getItem("setupObject");
    // console.log(setupObjectJSON);
    if (setupObjectJSON) {
        Object.assign(setupObject, JSON.parse(setupObjectJSON));

    } else {
        const inputDataJSON = localStorage.getItem("upload") || "{}";
        const inputData = JSON.parse(inputDataJSON);

        const colNames = Array.isArray(inputData?.data?.meta?.fields) ? inputData.data.meta.fields : [];
        const colInclude = new Array(colNames.length).fill(false);
        const uploadObjectJSON = localStorage.getItem("upload") || "{}";
        const uploadObject = JSON.parse(uploadObjectJSON);
        const uploadColNames = uploadObject.data.meta.fields;
        const uploadRows = uploadObject.data.data;
        let colValuesList: string[][] = [];
        let enumPriorityOrder: string[][] = [];
        for (let i = 0; i < colNames.length; i++) {

            let columnValues: string[] = [];
            for (let j = 0; j < uploadRows.length; j++) {
                const uploadColName = uploadColNames[i];
                const uploadRow = uploadObject.data.data[j];
                columnValues.push(uploadRow[uploadColName]);
            }
            colValuesList.push([...new Set(columnValues)]);
            enumPriorityOrder.push([]);
        }

        const newSetupObject: SetupObject = {
            colNames: colNames,
            colValues: colValuesList,
            colInclude: colInclude,
            enumPriorityOrder: enumPriorityOrder,
            priority: [],
            marketDates: [],
            tiers: [],
            locations: [],
            sections: [],
        };

        Object.assign(setupObject, newSetupObject);
        localStorage.setItem("setupObject", JSON.stringify(setupObject));
    }

    // retrieve view state
    const setupPageIdx = JSON.parse(localStorage.getItem("setupPageIdx") || "null");
    pageIdx.value = setupPageIdx === null ? 0 : setupPageIdx;
});

const handleUpdateSetupObject = (newSetupObject: SetupObject) => {
    nextTick(() => {
        Object.assign(setupObject, newSetupObject);
        localStorage.setItem("setupObject", JSON.stringify(setupObject));
    });
};

const handleNext = () => {
    pageIdx.value = pageIdx.value === maxPageIdx ? maxPageIdx : pageIdx.value + 1;
    localStorage.setItem("setupPageIdx", JSON.stringify(pageIdx.value));
    saveMarket();
}
const handleBack = () => {
    pageIdx.value = pageIdx.value === 0 ? 0 : pageIdx.value - 1;
    localStorage.setItem("setupPageIdx", JSON.stringify(pageIdx.value));
    saveMarket();
}
const handleDone = () => {
    router.push("/generate-assignment");
    saveMarket();
}

</script>

<template>
    <div class="market-setup-view">
        <div class="market-setup-body">
            <div class="settings-container">
                <div class="settings-header">
                    <h1>Settings</h1>
                </div>
                <div class="settings-body">
                    <template v-if="pageIdx === 0">
                        <div class="double-column-body">
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Manage Columns</h2>
                                </template>
                                <template #setting-content>
                                    <ElementSetupColumns :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Market Dates</h2>
                                </template>
                                <template #setting-content>
                                    <ElementMarketDates :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                        </div>
                    </template>

                    <template v-else-if="pageIdx === 2">
                        <div class="double-column-body">
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Assignment Priority</h2>
                                </template>
                                <template #setting-content>
                                    <ElementAssignmentPriority :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Assignment Options</h2>
                                </template>
                                <template #setting-content>
                                    <ElementAssignmentPriority :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                        </div>
                    </template>

                    <template v-else-if="pageIdx === 1">
                        <div class="triple-column-body">
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Tier Setup</h2>
                                </template>
                                <template #setting-content>
                                    <ElementTierSetup :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Location Setup</h2>
                                </template>
                                <template #setting-content>
                                    <ElementLocationSetup :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                            <ElementSettingContainer>
                                <template #setting-title>
                                    <h2>Section Setup</h2>
                                </template>
                                <template #setting-content>
                                    <ElementSectionSetup :setupObject="setupObject"
                                        @update:setupObject="handleUpdateSetupObject" />
                                </template>
                            </ElementSettingContainer>
                        </div>
                    </template>

                    <template v-else>
                        <h1>Something went wrong!</h1>
                    </template>
                </div>
            </div>
            <div style="width: 100%; display: flex; flex-direction: row; justify-content: space-between;">
                <div>
                    <button v-if="pageIdx !== 0" class="done-button" @click="handleBack">Back</button>
                </div>
                <div>
                    <button v-if="pageIdx === maxPageIdx" class="done-button" @click="handleDone">Done</button>
                    <button v-else class="done-button" @click="handleNext">Next</button>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.market-setup-view {
    width: 100%;
    min-width: 1000px;
    flex: 1;

    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.market-setup-body {
    width: 80%;
    height: 80%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.settings-container {
    align-self: stretch;
    flex: 1;
    background-color: white;
    box-shadow: 0px 0px 4px 5px rgba(0, 0, 0, 0.25);
    display: flex;
    flex-direction: column;
}

.settings-right-container {
    display: grid;
    grid-template-rows: 48% 4% 48%;
}

.settings-header {
    align-self: stretch;
    height: 50px;
    background-color: var(--mm-black);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
}

.settings-body {
    align-self: stretch;
    flex-grow: 1;
    display: flex;
    gap: 30px;
    padding: 40px;
    min-height: 0;
    flex: 1;
}

.single-column-body {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 1fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

.double-column-body {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

.triple-column-body {
    align-self: stretch;
    flex-grow: 1;
    display: grid;
    grid-template-columns: 1fr 1fr 2fr;
    gap: 30px;
    min-height: 0;
    flex: 1;
}

h1 {
    font-family: 'Outfit Regular';
    text-align: center;
    font-size: 30px;
    color: white;
}

h2 {
    font-family: 'Merge One';
    text-align: left;
    font-size: 20px;
    color: white;
}

.done-button {
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