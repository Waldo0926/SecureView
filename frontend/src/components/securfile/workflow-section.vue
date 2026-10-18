<script setup lang="ts">
import SentenceLines from '@/components/SentenceLines.vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Expand,
  Pause,
  Play,
  RotateCcw,
  X,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { workflowSlides } from '@/data/workflow-guide'

const STEP_MS = 3000
const slides = workflowSlides
const current = ref(0)
const playing = ref(true)
const inView = ref(false)
const pageVisible = ref(true)
const imageReady = ref(true)
const progress = ref(0)
const section = ref<HTMLElement | null>(null)
const lightbox = ref<HTMLDialogElement | null>(null)
const touchStartX = ref<number | null>(null)

const active = computed(() => slides[current.value]!)
const isLast = computed(() => current.value === slides.length - 1)
const isFirst = computed(() => current.value === 0)

let stepTimer: ReturnType<typeof setTimeout> | undefined
let progressRaf = 0
let progressStartedAt = 0
let observer: IntersectionObserver | undefined
const warmedImages = new Set<string>()

function stopTimers() {
  if (stepTimer !== undefined) clearTimeout(stepTimer)
  stepTimer = undefined
  if (progressRaf) cancelAnimationFrame(progressRaf)
  progressRaf = 0
  progress.value = 0
}

const { locale } = useI18n()
/** The screenshots exist in English and Chinese (`<name>-zh.webp`): show the set for the chosen language. */
const shot = (name: string) => `/walkthrough/${name}${locale.value === 'zh-CN' ? '-zh' : ''}.webp`

function warmSlide(index: number) {
  const slide = slides[index]
  if (!slide) return
  for (const name of [slide.id, slide.mobile]) {
    if (warmedImages.has(name)) continue
    warmedImages.add(name)
    const image = new Image()
    image.src = shot(name)
  }
}

function goTo(index: number) {
  playing.value = false
  const next = Math.max(0, Math.min(slides.length - 1, index))
  if (next === current.value) return
  imageReady.value = false
  current.value = next
}

function nextStep() {
  if (isLast.value) goTo(0)
  else goTo(current.value + 1)
}

function prevStep() {
  if (!isFirst.value) goTo(current.value - 1)
}

function togglePlayback() {
  if (isLast.value && !playing.value) {
    imageReady.value = false
    current.value = 0
  }
  playing.value = !playing.value
}

function enlarge() {
  playing.value = false
  lightbox.value?.showModal()
}

function onImageLoad() {
  imageReady.value = true
}

function onTouchStart(event: TouchEvent) {
  touchStartX.value = event.changedTouches[0]?.clientX ?? null
}

function onTouchEnd(event: TouchEvent) {
  const start = touchStartX.value
  const end = event.changedTouches[0]?.clientX
  touchStartX.value = null
  if (start == null || end == null) return
  const delta = end - start
  if (Math.abs(delta) < 48) return
  playing.value = false
  if (delta < 0) goTo(Math.min(slides.length - 1, current.value + 1))
  else goTo(Math.max(0, current.value - 1))
}

function syncVisibility() {
  pageVisible.value = document.visibilityState === 'visible'
}

function tickProgress() {
  if (!playing.value) return
  const elapsed = performance.now() - progressStartedAt
  progress.value = Math.min(1, elapsed / STEP_MS)
  if (progress.value < 1) {
    progressRaf = requestAnimationFrame(tickProgress)
  }
}

watch(current, () => {
  warmSlide((current.value + 1) % slides.length)
})

// Autoplay starts on. Pause, Back/Next, or picking a step turns it off.
// Off-screen or hidden tabs pause so the guide does not run while the visitor is elsewhere.
watch([playing, inView, pageVisible, current], () => {
  stopTimers()
  if (!playing.value || !inView.value || !pageVisible.value) return
  progressStartedAt = performance.now()
  progressRaf = requestAnimationFrame(tickProgress)
  stepTimer = setTimeout(() => {
    if (isLast.value) {
      playing.value = false
      progress.value = 1
      return
    }
    imageReady.value = false
    current.value += 1
  }, STEP_MS)
})

onMounted(() => {
  syncVisibility()
  document.addEventListener('visibilitychange', syncVisibility)
  warmSlide(0)
  warmSlide(1)
  observer = new IntersectionObserver(
    ([entry]) => {
      inView.value = entry?.isIntersecting ?? false
    },
    { threshold: 0.15 },
  )
  if (section.value) observer.observe(section.value)
})

onBeforeUnmount(() => {
  stopTimers()
  observer?.disconnect()
  document.removeEventListener('visibilitychange', syncVisibility)
})
</script>

<template>
  <section id="how-it-works" ref="section" class="guide-section py-20 md:py-28" aria-labelledby="guide-heading">
    <div class="container mx-auto px-4">
      <div class="mx-auto mb-9 max-w-3xl text-center">
        <p class="mb-3 text-xs uppercase font-mono tracking-[0.14em] text-muted-foreground">Picture guide</p>
        <h2 id="guide-heading" class="text-balance text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Your first share, one screen at a time
        </h2>
        <p class="mx-auto mt-4 text-muted-foreground">
          <SentenceLines text="Seven screenshots of the real website, from picking a file to your teammate downloading it." />
        </p>
      </div>

      <div class="mx-auto max-w-6xl">
        <div class="guide-prerequisite">
          <span class="font-semibold text-foreground">Before you start</span>
          <span>Sign in to SecureView. Keep your encryption passphrase handy.</span>
          <RouterLink to="/register" class="inline-flex min-h-10 shrink-0 items-center font-medium text-primary underline-offset-4 hover:underline">
            Need an account?
          </RouterLink>
        </div>

        <div
          class="guide-shell"
          tabindex="0"
          @keydown.left.prevent="prevStep"
          @keydown.right.prevent="isLast ? goTo(0) : goTo(current + 1)"
        >
          <nav class="guide-steps" aria-label="Walkthrough steps">
            <button
              v-for="(slide, index) in slides"
              :key="slide.id"
              type="button"
              class="guide-step"
              :class="{
                'is-current': current === index,
                'is-done': index < current,
              }"
              :aria-current="current === index ? 'step' : undefined"
              :aria-label="`Step ${index + 1}: ${slide.short}`"
              @click="goTo(index)"
            >
              <span class="guide-step-number">
                <Check v-if="index < current" class="h-3.5 w-3.5" aria-hidden="true" />
                <template v-else>{{ index + 1 }}</template>
              </span>
              <span>{{ slide.short }}</span>
            </button>
          </nav>

          <div
            class="guide-progress"
            role="progressbar"
            :aria-valuemin="0"
            :aria-valuemax="100"
            :aria-valuenow="Math.round(progress * 100)"
            :aria-hidden="!playing"
          >
            <span class="guide-progress-bar" :style="{ transform: `scaleX(${playing ? progress : 0})` }" />
          </div>

          <div
            class="guide-content"
            role="region"
            aria-roledescription="carousel"
            aria-label="How to upload and share a file"
            @touchstart.passive="onTouchStart"
            @touchend.passive="onTouchEnd"
          >
            <div class="guide-visual">
              <div class="guide-location">
                <span class="guide-location-dot" aria-hidden="true" />
                <span>{{ active.page }}</span>
                <span class="ml-auto shrink-0 text-xs uppercase tracking-wider">Actual interface</span>
              </div>
              <button
                type="button"
                class="guide-image-button"
                aria-label="Enlarge current screenshot"
                @click="enlarge"
              >
                <Transition name="guide-fade" mode="out-in">
                  <picture :key="active.id">
                    <source media="(max-width: 767px)" :srcset="shot(active.mobile)" />
                    <img
                      :src="shot(active.id)"
                      :alt="active.alt"
                      width="1410"
                      height="1000"
                      decoding="async"
                      :class="{ 'is-ready': imageReady }"
                      @load="onImageLoad"
                    />
                  </picture>
                </Transition>
                <span class="guide-zoom"><Expand class="h-3.5 w-3.5" /> Enlarge</span>
              </button>
              <p class="guide-image-note">
                <SentenceLines text="Look for the blue numbered outline. Screenshots use example data and Light mode. On a phone you can also swipe between steps." />
              </p>
            </div>

            <div class="guide-copy" :aria-live="playing ? 'off' : 'polite'" aria-atomic="true">
              <Transition name="guide-fade" mode="out-in">
                <div :key="active.id" class="flex h-full flex-col">
                  <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                    Step {{ current + 1 }} / {{ slides.length }}
                  </p>
                  <h3 class="mt-3 text-balance text-2xl font-semibold leading-tight tracking-tight text-foreground">
                    {{ active.title }}
                  </h3>
                  <p class="mt-5 text-sm leading-7 text-foreground"><SentenceLines :text="active.action" /></p>
                  <div class="guide-result">
                    <CheckCircle2 class="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                    <div>
                      <p class="text-xs font-semibold text-foreground">What happens next</p>
                      <p class="mt-1.5 text-sm leading-6 text-muted-foreground">{{ active.result }}</p>
                    </div>
                  </div>
                  <p class="guide-tip"><SentenceLines :text="active.tip" /></p>
                </div>
              </Transition>
            </div>
          </div>

          <div class="guide-controls">
            <button
              type="button"
              class="guide-play"
              :aria-label="playing ? 'Pause slideshow' : 'Play slideshow'"
              @click="togglePlayback"
            >
              <Pause v-if="playing" class="h-4 w-4" />
              <Play v-else class="h-4 w-4" />
              <span>{{ playing ? 'Pause' : 'Play slideshow' }}</span>
            </button>
            <div class="ml-auto flex items-center gap-2">
              <button
                type="button"
                class="guide-back"
                :disabled="isFirst"
                aria-label="Previous step"
                @click="prevStep"
              >
                <ArrowLeft class="h-4 w-4" />
                <span class="hidden sm:inline">Back</span>
              </button>
              <button type="button" class="guide-next" @click="isLast ? goTo(0) : goTo(current + 1)">
                <RotateCcw v-if="isLast" class="h-4 w-4" />
                {{ isLast ? 'Start again' : 'Next step' }}
                <ArrowRight v-if="!isLast" class="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <div class="guide-footer">
          <div>
            <p class="font-semibold text-foreground">Ready to try your first file?</p>
            <p class="mt-1 text-sm text-muted-foreground"><SentenceLines text="This is a picture guide. Start in Upload when you’re ready." /></p>
          </div>
          <RouterLink
            to="/upload"
            class="inline-flex h-11 shrink-0 items-center gap-2 rounded-full border border-primary/40 px-6 text-sm font-semibold text-primary transition-colors hover:bg-primary/10"
          >
            Try it with your file <ArrowRight class="h-4 w-4" />
          </RouterLink>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <dialog
        ref="lightbox"
        class="guide-lightbox"
        aria-label="Enlarged walkthrough screenshot"
        @click="($event.target === lightbox) && lightbox?.close()"
      >
        <div class="flex items-center justify-between gap-4 border-b border-border p-4">
          <p class="text-sm font-semibold text-foreground">Step {{ current + 1 }}: {{ active.short }}</p>
          <button type="button" class="guide-back" aria-label="Close enlarged screenshot" @click="lightbox?.close()">
            <X class="h-5 w-5" />
          </button>
        </div>
        <div class="guide-lightbox-image">
          <img :src="shot(active.id)" :alt="active.alt" />
        </div>
        <p class="p-4 text-sm leading-relaxed text-foreground"><SentenceLines :text="active.action" /></p>
      </dialog>
    </Teleport>
  </section>
</template>

<style scoped>
.guide-section {
  scroll-margin-top: 6rem;
}

.guide-prerequisite {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.5rem 1rem;
  margin-bottom: 1.5rem;
  font-size: 0.8125rem;
  color: var(--muted-foreground);
}

.guide-shell {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 1.5rem;
  background: var(--card);
  box-shadow: 0 18px 60px color-mix(in oklab, var(--foreground) 5%, transparent);
  outline: none;
}

.guide-shell:focus-visible {
  box-shadow:
    0 18px 60px color-mix(in oklab, var(--foreground) 5%, transparent),
    0 0 0 3px color-mix(in oklab, var(--ring) 45%, transparent);
}

.guide-steps {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  border-bottom: 1px solid var(--border);
  padding: 0.75rem;
  gap: 0.25rem;
}

.guide-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.55rem;
  border-radius: 0.75rem;
  padding: 0.75rem 0.25rem;
  color: var(--muted-foreground);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}

.guide-step:hover {
  background: var(--secondary);
  color: var(--foreground);
}

.guide-step.is-current {
  color: var(--primary);
  background: color-mix(in oklab, var(--primary) 8%, transparent);
}

.guide-step.is-done {
  color: var(--foreground);
}

.guide-step-number {
  display: grid;
  place-items: center;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 50%;
  border: 1px solid var(--border);
  font-size: 0.75rem;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.is-current .guide-step-number {
  background: var(--primary);
  color: var(--primary-foreground);
  border-color: var(--primary);
}

.is-done .guide-step-number {
  background: color-mix(in oklab, var(--primary) 16%, transparent);
  border-color: color-mix(in oklab, var(--primary) 35%, var(--border));
  color: var(--primary);
}

.guide-progress {
  height: 3px;
  background: color-mix(in oklab, var(--border) 80%, transparent);
}

.guide-progress-bar {
  display: block;
  height: 100%;
  width: 100%;
  transform-origin: left center;
  transform: scaleX(0);
  background: var(--primary);
  transition: none;
}

.guide-content {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(0, 1fr);
}

.guide-visual {
  min-width: 0;
  padding: 1.5rem;
  background: color-mix(in oklab, var(--secondary) 55%, var(--card));
  display: flex;
  flex-direction: column;
}

.guide-location {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0 0.15rem 1rem;
  font-size: 0.75rem;
  color: var(--muted-foreground);
  min-height: 2.3rem;
}

.guide-location-dot {
  width: 0.4rem;
  height: 0.4rem;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--primary);
}

.guide-image-button {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  width: 100%;
  min-height: 330px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 0.875rem;
  padding: 0.5rem;
  cursor: zoom-in;
  overflow: hidden;
}

.guide-image-button picture {
  display: block;
  width: 100%;
}

.guide-image-button img {
  display: block;
  width: 100%;
  height: 340px;
  object-fit: contain;
  opacity: 0;
  transition: opacity 0.28s ease;
}

.guide-image-button img.is-ready {
  opacity: 1;
}

.guide-zoom {
  position: absolute;
  bottom: 0.65rem;
  right: 0.65rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.65rem;
  border-radius: 2rem;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--foreground);
  font-size: 0.75rem;
}

.guide-image-note {
  padding: 0.9rem 0.15rem 0;
  font-size: 0.75rem;
  color: var(--muted-foreground);
  line-height: 1.6;
}

.guide-copy {
  display: flex;
  flex-direction: column;
  padding: 2.5rem 1.75rem 1.75rem;
  min-height: 500px;
}

.guide-result {
  display: flex;
  gap: 0.625rem;
  margin-top: 1.75rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
}

.guide-tip {
  margin-top: auto;
  padding-top: 1.5rem;
  font-size: 0.75rem;
  line-height: 1.8;
  color: var(--muted-foreground);
}

.guide-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
  border-top: 1px solid var(--border);
  padding: 1rem 1.5rem;
}

.guide-play,
.guide-back,
.guide-next {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  gap: 0.5rem;
  min-height: 2.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
}

.guide-play {
  color: var(--foreground);
}

.guide-back {
  border: 1px solid var(--border);
  border-radius: 0.65rem;
  padding: 0 0.85rem;
  color: var(--foreground);
}

.guide-back:disabled {
  opacity: 0.35;
  cursor: default;
}

.guide-back:not(:disabled):hover {
  background: var(--secondary);
}

.guide-next {
  padding: 0 1.25rem;
  border-radius: 0.65rem;
  background: var(--primary);
  color: var(--primary-foreground);
}

.guide-next:hover {
  opacity: 0.9;
}

.guide-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  margin-top: 1.75rem;
  padding: 0 0.5rem;
}

.guide-section button:focus-visible,
.guide-lightbox button:focus-visible {
  outline: 3px solid var(--ring);
  outline-offset: 3px;
}

.guide-lightbox {
  margin: auto;
  padding: 0;
  width: min(1100px, calc(100vw - 2rem));
  max-height: calc(100dvh - 2rem);
  border: 1px solid var(--border);
  border-radius: 1rem;
  background: var(--card);
  color: var(--foreground);
}

.guide-lightbox::backdrop {
  background: rgb(0 0 0 / 0.72);
}

.guide-lightbox-image {
  overflow: auto;
  background: #fff;
}

.guide-lightbox-image img {
  display: block;
  margin: auto;
  width: auto;
  max-width: 100%;
  max-height: 70dvh;
  object-fit: contain;
}

.guide-fade-enter-active,
.guide-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.guide-fade-enter-from,
.guide-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@media (max-width: 767px) {
  .guide-steps {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.35rem;
  }

  .guide-step {
    flex-direction: row;
    text-align: left;
    gap: 0.4rem;
    padding: 0.5rem;
    font-size: 0.75rem;
  }

  .guide-step-number {
    flex-shrink: 0;
    width: 1.3rem;
    height: 1.3rem;
  }

  .guide-content {
    display: flex;
    flex-direction: column;
  }

  .guide-copy {
    min-height: 0;
    padding: 1.5rem;
  }

  .guide-copy h3 {
    font-size: 1.35rem;
  }

  .guide-visual {
    padding: 1rem;
  }

  .guide-location {
    font-size: 0.75rem;
    flex-wrap: wrap;
  }

  .guide-location > span:last-child {
    display: none;
  }

  .guide-image-button {
    min-height: 240px;
  }

  .guide-image-button img {
    height: 290px;
  }

  .guide-result {
    margin-top: 1rem;
    padding-top: 1rem;
  }

  .guide-tip {
    padding-top: 1rem;
  }

  .guide-controls {
    padding: 0.75rem;
    gap: 0.5rem;
  }

  .guide-play {
    gap: 0.35rem;
    font-size: 0.75rem;
  }

  .guide-next {
    padding-inline: 0.8rem;
    font-size: 0.75rem;
  }

  .guide-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .guide-fade-enter-active,
  .guide-fade-leave-active,
  .guide-image-button img,
  .guide-step,
  .guide-step-number {
    transition: none;
  }

  .guide-fade-enter-from,
  .guide-fade-leave-to {
    transform: none;
  }
}
</style>
