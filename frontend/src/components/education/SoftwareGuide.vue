<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Clapperboard } from 'lucide-vue-next'
import { HELP_VIDEOS as guides } from '@/data/help-videos'

const route = useRoute()
const activeId = ref(guides[0]!.id)
const active = computed(() => guides.find((g) => g.id === activeId.value)!)

// `/help?video=<id>#videos` opens on that video, which is how the Help assistant links to one.
watch(
  () => route.query.video,
  (video) => {
    if (typeof video === 'string' && guides.some((g) => g.id === video)) activeId.value = video
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap gap-2" role="tablist" aria-label="Videos">
      <button
        v-for="guide in guides"
        :key="guide.id"
        type="button"
        role="tab"
        :aria-selected="activeId === guide.id"
        class="inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors"
        :class="
          activeId === guide.id
            ? 'border-primary bg-primary/10 text-foreground'
            : 'border-border bg-card text-muted-foreground hover:border-primary/40 hover:text-foreground'
        "
        @click="activeId = guide.id"
      >
        <Clapperboard class="h-3.5 w-3.5 text-primary" />
        <span>{{ guide.title }}</span>
        <span class="text-xs uppercase tracking-[0.14em] text-muted-foreground/80">{{ guide.tag }}</span>
      </button>
    </div>

    <article class="overflow-hidden rounded-xl border border-border bg-card" data-testid="help-video">
      <div class="border-b border-border px-5 py-4">
        <p class="mb-2 text-xs uppercase tracking-[0.22em] text-muted-foreground">{{ active.tag }}</p>
        <h3 class="text-xl font-bold text-foreground">{{ active.title }}</h3>
        <p class="mt-2 text-sm text-muted-foreground">{{ active.summary }}</p>
      </div>

      <div class="grid gap-0 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="bg-black/90">
          <video
            :key="active.id"
            class="aspect-video h-auto w-full"
            controls
            playsinline
            preload="metadata"
            :src="active.videoSrc"
            :poster="active.poster"
            :aria-label="active.title"
          />
        </div>
        <div class="border-t border-border p-5 lg:border-l lg:border-t-0">
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">In this video</p>
          <ol class="mt-3 space-y-2 text-sm text-foreground">
            <li v-for="(step, i) in active.steps" :key="step" class="flex gap-2">
              <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{{ i + 1 }}</span>
              <span>{{ step }}</span>
            </li>
          </ol>
        </div>
      </div>
    </article>
  </div>
</template>
