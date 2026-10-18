<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppHeader from '@/components/securfile/header.vue'
import AppFooter from '@/components/securfile/footer.vue'
import AppSidebar from '@/components/securfile/AppSidebar.vue'
import HelpAssistant from '@/components/assistant/HelpAssistant.vue'
import { useTheme } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth_store'

const route = useRoute()
const auth = useAuthStore()
/**
 * Signed in and anywhere except the home page and the sign-in pages: those get the sidebar instead of
 * the marketing header. Help, Education and Contact us used to swap the sidebar for the marketing
 * header, which felt like jumping to another site.
 */
const inApp = computed(() => auth.isAuthed && route.path !== '/' && route.meta.guestOnly !== true)
const isScrolled = ref(false)
const isMobileMenuOpen = ref(false)
const { preference, setPreference } = useTheme()

watch(
  () => route.fullPath,
  () => {
    isMobileMenuOpen.value = false
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  },
)

const onScroll = () => {
  isScrolled.value = window.scrollY > 20
}

onMounted(() => {
  window.addEventListener('scroll', onScroll)
  onScroll()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<template>
  <main class="min-h-screen bg-background" :class="inApp ? 'lg:flex' : ''">
    <AppSidebar v-if="inApp" />
    <div class="min-w-0 flex-1">
    <AppHeader
      :in-app="inApp"
      :is-scrolled="isScrolled"
      :is-mobile-menu-open="isMobileMenuOpen"
      :theme-preference="preference"
      @toggle-mobile-menu="isMobileMenuOpen = !isMobileMenuOpen"
      @close-mobile-menu="isMobileMenuOpen = false"
      @set-theme-preference="setPreference"
    />
    <RouterView />
    <div :class="inApp ? 'lg:hidden' : ''"><AppFooter /></div>
    </div>
    <HelpAssistant />
  </main>
</template>
