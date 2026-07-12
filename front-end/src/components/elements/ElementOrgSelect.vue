<script setup lang="ts">
import { ref, onMounted } from 'vue';
import {
    type Organization,
    type OrganizationRoleType,
    type ThemeObject,
} from '@/assets/types/datatypes';
import { api, getApiErrorMessage } from '@/utils/api';

type RawOrganization = {
    id: string;
    name: string;
    owner: string;
    admins?: string[];
    members?: string[];
    markets?: string[];
    ownerEmail?: string;
    owner_email?: string;
    adminEmails?: string[];
    admin_emails?: string[];
    memberEmails?: string[];
    member_emails?: string[];
    theme?: ThemeObject;
    userRole?: OrganizationRoleType;
    user_role?: OrganizationRoleType;
};

const model = defineModel<string>({ required: true });

const organizations = ref<Organization[]>([]);
const loading = ref(true);
const errorMessage = ref('');

function parseOrgFromApi(org: RawOrganization): Organization {
    const userRole = org.userRole ?? org.user_role;
    return {
        id: org.id,
        name: org.name,
        owner: org.owner,
        admins: org.admins || [],
        members: org.members || [],
        markets: org.markets || [],
        ownerEmail: org.ownerEmail ?? org.owner_email,
        adminEmails: org.adminEmails ?? org.admin_emails,
        memberEmails: org.memberEmails ?? org.member_emails,
        theme: org.theme,
        userRole: userRole ?? undefined,
    };
}

async function fetchOrganizations() {
    loading.value = true;
    errorMessage.value = '';
    try {
        const response = await api.get('/organizations');
        organizations.value = (response.data.organizations || []).map(parseOrgFromApi);
    } catch (err) {
        errorMessage.value = getApiErrorMessage(err, 'Failed to load organizations');
        organizations.value = [];
    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    fetchOrganizations();
});
</script>

<template>
    <div class="org-select-wrapper">
        <select
            v-model="model"
            class="org-select"
            :disabled="loading || organizations.length === 0"
            data-testid="org-select-dropdown"
        >
            <option value="" disabled>Select organization</option>
            <option
                v-for="org in organizations"
                :key="org.id"
                :value="org.id"
            >
                {{ org.name }}
            </option>
        </select>
        <p v-if="loading" class="org-select-hint">Loading organizations...</p>
        <p v-else-if="errorMessage" class="org-select-error">{{ errorMessage }}</p>
        <p v-else-if="organizations.length === 0" class="org-select-hint">
            No organizations available.
            <a href="/organizations" class="org-select-link">Create an organization</a>
        </p>
    </div>
</template>

<style scoped>
.org-select-wrapper {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
}

.org-select {
    width: 100%;
    padding: 8px 12px;
    border: 1.5px solid var(--mm-grey);
    border-radius: 6px;
    font-size: 14px;
    font-family: 'Outfit Regular', sans-serif;
    background: white;
    text-align: center;
}

.org-select:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.org-select-hint {
    font-size: 12px;
    color: #666;
    margin: 0;
}

.org-select-error {
    font-size: 12px;
    color: #d32f2f;
    margin: 0;
}

.org-select-link {
    color: var(--mm-black);
    text-decoration: underline;
    font-weight: 600;
}
</style>
