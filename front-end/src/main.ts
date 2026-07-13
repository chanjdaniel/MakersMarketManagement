import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './stores/floorplan'
import VueKonva from 'vue-konva'

import App from './App.vue'
import router from './router'
import { PrimeVue } from '@primevue/core'
import { installApplicantSessionExpiry } from './utils/applicantSessionExpiry'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(PrimeVue)
app.use(VueKonva)

// An expired applicant session ends in the one place that can both drop the token and send the
// applicant somewhere they can do something about it. See `applicantSessionExpiry`.
installApplicantSessionExpiry(router)

app.mount('#app')
