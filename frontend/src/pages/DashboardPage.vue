<script setup lang="ts">
import { ArrowRight } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'

import HeroSection from '@/components/securfile/hero-section.vue'
import HomeMoves from '@/components/securfile/home-moves.vue'
import WorkflowSection from '@/components/securfile/workflow-section.vue'
import WhySecureView from '@/components/explainers/WhySecureView.vue'
</script>

<template>
  <HeroSection />
  <HomeMoves />

  <section class="bg-secondary/30 py-20" aria-labelledby="why-home-heading">
    <div class="page-container">
      <div class="mx-auto mb-10 max-w-3xl text-center">
        <p class="mb-3 text-xs uppercase font-mono tracking-[0.14em] text-muted-foreground">Why SecureView</p>
        <h2 id="why-home-heading" class="text-balance text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Compared with ordinary cloud storage
        </h2>
      </div>
      <WhySecureView />
      <div class="mt-8 text-center">
        <RouterLink to="/how-it-works" class="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
          The full explainer and a four-step quick start <ArrowRight class="h-4 w-4" />
        </RouterLink>
      </div>
    </div>
  </section>

  <WorkflowSection />
</template>
