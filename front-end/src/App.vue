<script setup lang="ts">
// npm run dev
import axios from 'axios';
import { RouterView } from 'vue-router'
import ElementBanner from './components/elements/ElementBanner.vue'
import ElementNavigation from './components/elements/ElementNavigation.vue';

import { onMounted, ref, provide, computed, watch } from 'vue';
import { useRoute, useRouter } from "vue-router";

const hostname = import.meta.env.VITE_FLASK_HOST;

const navOpen = ref(false);
const route = useRoute();
const router = useRouter();
const isLogin = computed(() => route.path === "/login");

const user = ref<string | null>(null);
const setUser = (user_data: string | null) => {
  user.value = user_data;
};

provide("user", user);
provide("setUser", setUser);

/**
 * Whether the page being shown is one of the product's public ones: check-in, and every applicant
 * screen. Read from the same `meta.public` the router guard reads, because two answers to "is this
 * page public" is one answer too many - the guard would let a visitor in and this would throw them
 * straight back out.
 */
const onPublicRoute = () => router.currentRoute.value.matched.some(
  (record) => record.meta.public === true,
);

/**
 * The same question, asked of the page currently on screen, for layout rather than for auth.
 *
 * The organizer's shell is 1000px wide at its narrowest: its views are tables, floorplans and market
 * setup, and squeezing those onto a phone is not what this class is for. The public pages are the
 * opposite - an applicant reaches the application form from a link, with no account, most often on a
 * phone - and inheriting that floor renders every one of them zoomed out and scrolled sideways. So
 * the floor belongs to the organizer shell, not to the app.
 */
const isPublicPage = computed(() =>
  route.matched.some((record) => record.meta.public === true),
);

onMounted(async () => {
  try {
    const response = await axios.get(`${hostname}/check-session`, {
      withCredentials: true,
    });

    if (response.status === 200) {
      const user_email = response.data.email;
      localStorage.setItem("user", JSON.stringify(user_email));
      setUser(user_email);
      return;
    }
  } catch {
    // No organizer session. Whether that is a problem depends entirely on where we are.
  }

  localStorage.clear();

  // Every route component is lazily imported, so the first navigation is still in flight while this
  // probe is: asking where we are before it lands asks about no page at all, whose answer to "is it
  // public" is no. That is a race an applicant loses whenever their chunk is slower than the
  // session check - on a cold load, most times.
  await router.isReady();

  // Having no session on a public route is not a problem to fix: those pages are reached by
  // applicants and by vendors checking in, none of whom have an organizer account at all, so
  // anonymous is the normal state there. Sending them to the organizer's sign-in page would make
  // every public page in this product unreachable for precisely the people it exists for.
  if (onPublicRoute()) return;

  router.push("/login");
});

watch(isLogin, (newValue) => {
  if (newValue) {
    navOpen.value = false;
  }
});

</script>

<template>
  <div class="app-container" :class="{ 'public-shell': isPublicPage }">
    <header>
      <ElementBanner @menuOpen="navOpen = true" :isLogin="isLogin"/>
    </header>

    <RouterView class="router-view"/>

    <div
      class="nav-background"
      :style="{
        opacity: navOpen ? '100%' : '0%', 
        visibility: navOpen ? 'visible' : 'hidden'
      }"
      @click="navOpen = false">
    </div>
    
    <ElementNavigation
      class="nav-bar"
      :style="{ left: navOpen ? '0px' : '-300px' }"
      @menuClose="navOpen = false"
      />
  </div>
</template>

<style scoped>

.app-container {
  width: 100vw;
  height: 100vh;
  min-width: 1000px;
  background-color: white;
  padding: 0px;
  margin: 0px;
  position: absolute;
  left: 0;
  top: 0;

  display: flex;
  flex-direction: column;
}

header {
  /* position: fixed;
  top: 0;
  left: 0; */
  width: 100vw;
  line-height: 1.5;
  max-height: 100vh;
}

.logo {
  display: block;
  margin: 0 auto 2rem;
}

.nav-bar {
  position: fixed;
  top: 0;
  left: -300px;
  transition: left 0.3s ease-in-out;
}

.nav-bar.nav-open {
  left: 0;
}

.nav-background {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.5);
  opacity: 100%;
  transition: opacity 0.3s ease-in-out, visibility 0.3s ease-in-out;
}

.banner {

  width: 100vw;
  height: 5vh;
}

.router-view {
  flex: 1;
  min-height: 0;
  min-width: 1000px;
}

/* A public page is the only page in this product a phone is likely to open, and the width floor
   above is the organizer shell's, not the app's. Dropped on both boxes, because either one left at
   1000px is enough to push the page sideways on its own. */
.app-container.public-shell,
.public-shell .router-view {
  min-width: 0;
}
</style>
