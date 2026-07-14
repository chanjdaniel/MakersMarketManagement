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

// Mounting before the first navigation resolves paints a page the app cannot yet name: route
// components are lazily imported, so `route.matched` is empty until the chunk lands, and every
// question the shell asks about the page - starting with whether it is a public one - is answered
// about no page at all. `App.vue` would lay the organizer's 1000px width floor over an applicant's
// phone for that first frame, which is a visible flash of the sideways-scrolled layout the floor was
// scoped away from those pages to prevent.
router.isReady().then(() => app.mount('#app'))
