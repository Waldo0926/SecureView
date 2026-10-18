<script setup lang="ts">
import { ArrowRight, ArrowUp, FileCheck2, LockKeyhole, Mail, ServerOff, Users } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SecureViewMark from '@/components/brand/SecureViewMark.vue'

const { t } = useI18n()

/**
 * The site footer. Every link goes to a page that exists: it used to list Privacy Policy, Terms of
 * Service, GitHub, X and Discord, all pointing at "#", so a click landed wherever the router sent
 * an empty hash. The first column mirrors the header, in the same order.
 */
const productLinks = [
  { label: 'nav.product', to: '/#features' },
  { label: 'nav.howItWorks', to: '/how-it-works' },
  { label: 'nav.help', to: '/help' },
  { label: 'nav.education', to: '/education' },
  { label: 'nav.contact', to: '/team' },
]
const learnLinks = [
  { label: 'footer.animatedExplainer', to: '/how-it-works' },
  { label: 'footer.walkthroughVideos', to: '/help#videos' },
  { label: 'footer.pictureGuide', to: '/#how-it-works' },
  { label: 'footer.algorithmExplorer', to: '/education' },
]
const promises = [
  { icon: LockKeyhole, text: 'footer.promiseBrowser' },
  { icon: ServerOff, text: 'footer.promiseNoKey' },
  { icon: FileCheck2, text: 'footer.promiseTamper' },
]
const FEEDBACK = 'mailto:swen0027@student.monash.edu?subject=%5BSecureView%5D%20Feedback'

function backToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <footer class="border-t border-border bg-card/50">
    <div class="container mx-auto px-4 py-14">
      <div class="grid gap-10 md:grid-cols-12">
        <div class="min-w-0 md:col-span-12 lg:col-span-5">
          <RouterLink
            to="/"
            class="mb-4 inline-flex w-fit items-center text-foreground"
            :aria-label="t('nav.homeAria')"
          >
            <SecureViewMark variant="logo" class="h-8" />
          </RouterLink>
          <p class="text-sm leading-relaxed text-muted-foreground">
            {{ t('footer.blurb') }}
          </p>
          <ul class="mt-5 space-y-2.5">
            <li v-for="item in promises" :key="item.text" class="flex items-center gap-2.5 text-sm text-foreground">
              <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <component :is="item.icon" class="h-4 w-4" />
              </span>
              {{ t(item.text) }}
            </li>
          </ul>
        </div>

        <nav class="min-w-0 md:col-span-4 lg:col-span-2" :aria-label="t('footer.productAria')">
          <h4 class="mb-3 text-sm font-semibold text-foreground">{{ t('footer.product') }}</h4>
          <ul class="text-sm">
            <li v-for="link in productLinks" :key="link.label">
              <RouterLink :to="link.to" class="inline-flex min-h-9 items-center text-muted-foreground transition-colors hover:text-foreground">{{ t(link.label) }}</RouterLink>
            </li>
          </ul>
        </nav>

        <nav class="min-w-0 md:col-span-4 lg:col-span-2" :aria-label="t('footer.learnAria')">
          <h4 class="mb-3 text-sm font-semibold text-foreground">{{ t('footer.learn') }}</h4>
          <ul class="text-sm">
            <li v-for="link in learnLinks" :key="link.label">
              <RouterLink :to="link.to" class="inline-flex min-h-9 items-center text-muted-foreground transition-colors hover:text-foreground">{{ t(link.label) }}</RouterLink>
            </li>
          </ul>
        </nav>

        <!-- Short facts in the same rhythm as the link lists beside it, instead of a sentence squeezed
             into a narrow column. The brand block and three columns fill all twelve tracks, so no empty
             track is left in the middle. On a tablet the brand block takes the first row and the three columns share the second. -->
        <div class="min-w-0 md:col-span-4 lg:col-span-3">
          <h4 class="mb-3 text-sm font-semibold text-foreground">{{ t('footer.projectHeading') }}</h4>
          <ul class="text-sm">
            <li class="flex min-h-9 items-center text-muted-foreground">{{ t('footer.projectUniversity') }}</li>
            <li class="flex min-h-9 items-center font-mono text-xs tracking-wide text-muted-foreground">FIT3161 / FIT3162</li>
            <li class="flex min-h-9 items-center text-muted-foreground">{{ t('footer.projectTeam') }}</li>
            <li class="flex min-h-9 items-center text-muted-foreground">{{ t('footer.projectSupervisor') }}</li>
            <li>
              <RouterLink to="/team" class="group inline-flex min-h-9 items-center gap-1.5 font-medium text-foreground hover:underline underline-offset-4">
                <Users class="h-4 w-4" /> {{ t('footer.meetTeam') }}
                <ArrowRight class="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden="true" />
              </RouterLink>
            </li>
          </ul>
        </div>
      </div>

      <div class="mt-12 flex flex-col items-center justify-between gap-3 border-t border-border pt-6 sm:flex-row">
        <p class="text-sm text-muted-foreground">{{ t('footer.copyright') }}</p>
        <div class="flex items-center gap-1 text-sm">
          <a :href="FEEDBACK" class="inline-flex min-h-10 items-center gap-1.5 rounded-md px-2.5 text-muted-foreground transition-colors hover:text-foreground">
            <Mail class="h-4 w-4" /> {{ t('footer.sendFeedback') }}
          </a>
          <button type="button" class="inline-flex min-h-10 items-center gap-1.5 rounded-md px-2.5 text-muted-foreground transition-colors hover:text-foreground" @click="backToTop">
            <ArrowUp class="h-4 w-4" /> {{ t('footer.backToTop') }}
          </button>
        </div>
      </div>
    </div>
  </footer>
</template>
