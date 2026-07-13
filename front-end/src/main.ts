import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './stores/floorplan'
import VueKonva from 'vue-konva'

import App from './App.vue'
import router from './router'
import { PrimeVue } from '@primevue/core'
import { setApplicantSessionExpiredHandler } from './utils/applicantApi'
import { useApplicationStore } from './stores/application'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(PrimeVue)
app.use(VueKonva)

// An expired applicant session ends here, in the one place that can both drop the token and send
// the applicant somewhere they can do something about it.
setApplicantSessionExpiredHandler(() => {
  useApplicationStore().endExpiredSession()
  router.push({
    name: 'applicant-login',
    params: { marketSlug: router.currentRoute.value.params.marketSlug },
  })
})

app.mount('#app')
