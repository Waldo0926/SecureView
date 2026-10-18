<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from 'lucide-vue-next'

import { STORY_SCENES, sceneDuration } from '@/data/security-story'

/**
 * An animated explainer of what happens to a file in SecureView, from Alice's browser through
 * the server to Bob's, and what happens when someone tampers with it.
 *
 * The stage is one SVG whose parts appear and move as the scene advances; the captions come
 * from `src/data/security-story.ts`. It plays by itself once it scrolls into view, pauses when
 * the viewer takes control, and with reduced motion it never autoplays and does not animate.
 * `autoplay` starts at once (for the recorded video); `compact` drops the step list.
 * Each scene stays up for `sceneDuration` (about 3 s) unless `sceneMs` fixes one length
 * for every scene, which the full-screen recording does.
 */
const props = withDefaults(defineProps<{ autoplay?: boolean; compact?: boolean; sceneMs?: number }>(), {
  autoplay: false,
  compact: false,
  sceneMs: undefined,
})

const scenes = STORY_SCENES
const index = ref(0)
const playing = ref(false)
const elapsed = ref(0)
const root = ref<HTMLElement | null>(null)
const reducedMotion = ref(false)

const scene = computed(() => scenes[index.value]!)
const at = (id: (typeof scenes)[number]['id']) => index.value >= scenes.findIndex((s) => s.id === id)
const is = (id: (typeof scenes)[number]['id']) => scene.value.id === id
const atEnd = computed(() => index.value === scenes.length - 1)
const sceneMs = computed(() => props.sceneMs ?? sceneDuration(scene.value))

let timer: number | undefined
let lastTick = 0
function tick(now: number) {
  if (!playing.value) return
  elapsed.value += now - lastTick
  lastTick = now
  if (elapsed.value >= sceneMs.value) {
    if (atEnd.value) {
      playing.value = false
      elapsed.value = sceneMs.value
      return
    }
    index.value += 1
    elapsed.value = 0
  }
  timer = requestAnimationFrame(tick)
}

function play() {
  if (atEnd.value && elapsed.value >= sceneMs.value) restart()
  playing.value = true
  lastTick = performance.now()
  cancelAnimationFrame(timer ?? 0)
  timer = requestAnimationFrame(tick)
}
function pause() {
  playing.value = false
  cancelAnimationFrame(timer ?? 0)
}
function go(to: number) {
  pause()
  index.value = Math.max(0, Math.min(scenes.length - 1, to))
  elapsed.value = 0
}
function restart() {
  index.value = 0
  elapsed.value = 0
}
const progress = computed(() => Math.min(1, elapsed.value / sceneMs.value))

let observer: IntersectionObserver | null = null
let started = false
onMounted(() => {
  reducedMotion.value =
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (props.autoplay) {
    started = true
    play()
    return
  }
  if (reducedMotion.value || typeof IntersectionObserver === 'undefined' || !root.value) return
  observer = new IntersectionObserver(
    (entries) => {
      if (!started && entries.some((e) => e.isIntersecting && e.intersectionRatio > 0.5)) {
        started = true
        play()
      }
    },
    { threshold: [0.5] },
  )
  observer.observe(root.value)
})
onBeforeUnmount(() => {
  pause()
  observer?.disconnect()
})

// Keyboard: left and right arrows step, space toggles, when the explainer has focus.
function onKey(event: KeyboardEvent) {
  if (event.key === 'ArrowRight') go(index.value + 1)
  else if (event.key === 'ArrowLeft') go(index.value - 1)
  else if (event.key === ' ') {
    event.preventDefault()
    if (playing.value) pause()
    else play()
  } else return
}

// Restart the per-scene CSS animations (the packets travelling) whenever the scene changes.
const sceneKey = ref(0)
watch(index, () => {
  sceneKey.value += 1
})
</script>

<template>
  <div
    ref="root"
    class="story"
    :class="{ 'story--still': reducedMotion }"
    tabindex="0"
    role="region"
    aria-roledescription="animated explainer"
    aria-label="How SecureView protects a file"
    data-testid="security-story"
    @keydown="onKey"
  >
    <div class="overflow-hidden rounded-2xl border border-border bg-card">
      <!-- The stage -->
      <svg
        viewBox="0 0 960 420"
        class="block h-auto w-full"
        role="img"
        :aria-label="`${scene.title}. ${scene.body}`"
        :data-scene="scene.id"
      >
        <defs>
          <marker id="story-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" class="fill-muted" />
          </marker>
        </defs>

        <!-- connections -->
        <line x1="270" y1="215" x2="352" y2="215" class="wire" marker-end="url(#story-arrow)" />
        <line x1="608" y1="215" x2="688" y2="215" class="wire" marker-end="url(#story-arrow)" />

        <!-- ===== Alice's browser ===== -->
        <g>
          <rect x="16" y="56" width="254" height="318" rx="14" class="panel" />
          <rect x="16" y="56" width="254" height="34" rx="14" class="panel-bar" />
          <circle cx="36" cy="73" r="4" class="dot" /><circle cx="50" cy="73" r="4" class="dot" /><circle cx="64" cy="73" r="4" class="dot" />
          <text x="143" y="78" text-anchor="middle" class="label strong">Alice’s browser</text>

          <!-- the document -->
          <g transform="translate(58 110)">
            <rect width="120" height="150" rx="8" class="doc" :class="{ 'doc--cipher': at('encrypt') }" />
            <g class="fade" :class="{ 'is-hidden': at('encrypt') }">
              <rect x="16" y="22" width="88" height="7" rx="3" class="ink strong-ink" />
              <rect x="16" y="40" width="80" height="5" rx="2.5" class="ink" />
              <rect x="16" y="54" width="88" height="5" rx="2.5" class="ink" />
              <rect x="16" y="68" width="64" height="5" rx="2.5" class="ink" />
              <rect x="16" y="88" width="88" height="5" rx="2.5" class="ink" />
              <rect x="16" y="102" width="72" height="5" rx="2.5" class="ink" />
              <rect x="16" y="116" width="84" height="5" rx="2.5" class="ink" />
            </g>
            <g class="fade" :class="{ 'is-hidden': !at('encrypt') }">
              <text x="18" y="32" class="hex">9f 3a c1 7e</text>
              <text x="18" y="52" class="hex">e8 41 b0 5d</text>
              <text x="18" y="72" class="hex">27 f6 0a 8b</text>
              <text x="18" y="92" class="hex">d1 64 c9 15</text>
              <!-- lock badge -->
              <g transform="translate(60 122)">
                <circle r="16" class="badge" />
                <rect x="-7" y="-2" width="14" height="10" rx="2" class="badge-ink" />
                <path d="M-4.5,-2 v-3.5 a4.5,4.5 0 0 1 9,0 v3.5" class="badge-stroke" />
              </g>
            </g>
          </g>
          <text x="118" y="282" text-anchor="middle" class="label">{{ at('encrypt') ? 'Q3 report.pdf · encrypted' : 'Q3 report.pdf' }}</text>

          <!-- the file key: appears when encrypting, then gets sealed -->
          <g class="pop" :class="{ 'is-hidden': !is('encrypt') }" transform="translate(226 150)">
            <circle r="22" class="key-bg" />
            <circle cx="-6" cy="0" r="7" class="key" />
            <path d="M0,0 h14 m-4,0 v6 m-5,-6 v5" class="key-stroke" />
            <text y="40" text-anchor="middle" class="tiny">new file key</text>
          </g>

          <!-- sealed keys: Alice's, and the offline recovery copy -->
          <g class="pop" :class="{ 'is-hidden': !at('wrap') }" transform="translate(196 316)">
            <g transform="translate(-36 0)">
              <rect x="-20" y="-14" width="40" height="28" rx="4" class="env env--alice" />
              <path d="M-20,-14 L0,2 L20,-14" class="env-flap" />
              <text y="30" text-anchor="middle" class="tiny">for Alice</text>
            </g>
            <g transform="translate(22 0)">
              <rect x="-20" y="-14" width="40" height="28" rx="4" class="env env--recovery" />
              <path d="M-20,-14 L0,2 L20,-14" class="env-flap" />
              <text y="30" text-anchor="middle" class="tiny">recovery</text>
            </g>
          </g>

          <!-- re-sealing for Bob, while sharing -->
          <g class="pop" :class="{ 'is-hidden': !is('share') }" transform="translate(76 316)">
            <rect x="-20" y="-14" width="40" height="28" rx="4" class="env env--bob" />
            <path d="M-20,-14 L0,2 L20,-14" class="env-flap" />
            <text y="30" text-anchor="middle" class="tiny">for Bob</text>
          </g>
        </g>

        <!-- ===== Server ===== -->
        <g>
          <rect x="354" y="86" width="254" height="258" rx="14" class="panel" />
          <rect x="354" y="86" width="254" height="34" rx="14" class="panel-bar" />
          <text x="481" y="108" text-anchor="middle" class="label strong">SecureView server</text>

          <!-- database -->
          <g transform="translate(400 150)">
            <ellipse cx="34" cy="8" rx="34" ry="9" class="db" />
            <path d="M0,8 v58 a34,9 0 0 0 68,0 v-58" class="db" />
            <path d="M0,30 a34,9 0 0 0 68,0 M0,50 a34,9 0 0 0 68,0" class="db-line" />
          </g>

          <g class="fade" :class="{ 'is-hidden': !at('upload') }">
            <g transform="translate(490 144)">
              <rect width="92" height="78" rx="6" class="doc doc--cipher" :class="{ 'doc--tampered': is('tamper') }" />
              <text x="10" y="22" class="hex small">9f 3a c1 7e</text>
              <text x="10" y="40" class="hex small" :class="{ 'hex--bad': is('tamper') }">{{ is('tamper') ? 'e8 FF b0 5d' : 'e8 41 b0 5d' }}</text>
              <text x="10" y="58" class="hex small">27 f6 0a 8b</text>
            </g>
            <text x="536" y="240" text-anchor="middle" class="tiny">ciphertext + SHA-256</text>
            <!-- sealed keys held by the server -->
            <g transform="translate(408 268)">
              <rect x="0" y="0" width="30" height="20" rx="3" class="env env--alice" />
              <rect x="38" y="0" width="30" height="20" rx="3" class="env env--recovery" />
              <rect x="76" y="0" width="30" height="20" rx="3" class="env env--bob" :class="{ 'is-hidden': !at('share') }" />
              <text x="55" y="38" text-anchor="middle" class="tiny">sealed keys only</text>
            </g>
          </g>

          <!-- intruder: sees only noise -->
          <g class="pop" :class="{ 'is-hidden': !is('upload') }" transform="translate(648 52)">
            <!-- a hooded figure with a mask: someone who got into the server -->
            <path d="M-17,26 a17,15 0 0 1 34,0 z" class="intruder" />
            <circle cy="2" r="11" class="intruder" />
            <rect x="-9" y="-1" width="18" height="5" rx="2.5" class="intruder-mask" />
            <g transform="translate(-178 -36)">
              <rect width="150" height="30" rx="8" class="bubble" />
              <text x="75" y="20" text-anchor="middle" class="tiny strong">intruder: “…just noise?”</text>
            </g>
          </g>

          <text v-if="is('tamper')" x="481" y="370" text-anchor="middle" class="label bad">one stored byte was changed</text>
        </g>

        <!-- ===== Bob's browser ===== -->
        <g>
          <rect x="690" y="56" width="254" height="318" rx="14" class="panel" :class="{ 'panel--dim': !at('share') }" />
          <rect x="690" y="56" width="254" height="34" rx="14" class="panel-bar" />
          <circle cx="710" cy="73" r="4" class="dot" /><circle cx="724" cy="73" r="4" class="dot" /><circle cx="738" cy="73" r="4" class="dot" />
          <text x="817" y="78" text-anchor="middle" class="label strong">Bob’s browser</text>

          <!-- passphrase unlock -->
          <g class="fade" :class="{ 'is-hidden': !at('open') }" transform="translate(722 108)">
            <rect width="190" height="30" rx="8" class="field" />
            <text x="12" y="20" class="tiny">passphrase</text>
            <text x="100" y="21" class="tiny strong">••••••••</text>
          </g>

          <!-- result: the readable file, or the refusal -->
          <g class="fade" :class="{ 'is-hidden': !is('open') }" transform="translate(757 152)">
            <rect width="120" height="150" rx="8" class="doc" />
            <rect x="16" y="22" width="88" height="7" rx="3" class="ink strong-ink" />
            <rect x="16" y="40" width="80" height="5" rx="2.5" class="ink" />
            <rect x="16" y="54" width="88" height="5" rx="2.5" class="ink" />
            <rect x="16" y="68" width="64" height="5" rx="2.5" class="ink" />
            <rect x="16" y="88" width="88" height="5" rx="2.5" class="ink" />
            <g transform="translate(96 126)">
              <circle r="16" class="ok" />
              <path d="M-7,0 l5,5 l9,-10" class="ok-stroke" />
            </g>
            <text x="60" y="170" text-anchor="middle" class="tiny ok-text">tag and SHA-256 verified</text>
          </g>
          <g class="fade" :class="{ 'is-hidden': !is('tamper') }" transform="translate(757 152)">
            <rect width="120" height="150" rx="8" class="doc doc--refused" />
            <g transform="translate(60 62)">
              <circle r="26" class="bad-bg" />
              <path d="M-10,-10 l20,20 m0,-20 l-20,20" class="bad-stroke" />
            </g>
            <text x="60" y="118" text-anchor="middle" class="tiny bad strong">download refused</text>
            <text x="60" y="170" text-anchor="middle" class="tiny">admin restores the original</text>
          </g>
        </g>

        <!-- ===== Travelling packets, replayed on each scene ===== -->
        <g :key="sceneKey">
          <g v-if="is('upload')" class="packet packet--to-server">
            <rect x="238" y="200" width="34" height="28" rx="5" class="doc doc--cipher" />
            <rect x="242" y="228" width="22" height="14" rx="3" class="env env--alice" />
          </g>
          <g v-if="is('share')" class="packet packet--to-server">
            <rect x="240" y="203" width="30" height="22" rx="3" class="env env--bob" />
          </g>
          <g v-if="is('open') || is('tamper')" class="packet packet--to-bob">
            <rect x="578" y="200" width="34" height="28" rx="5" class="doc doc--cipher" :class="{ 'doc--tampered': is('tamper') }" />
            <rect x="582" y="228" width="22" height="14" rx="3" class="env env--bob" />
          </g>
        </g>
      </svg>

      <!-- Caption -->
      <div class="border-t border-border px-5 py-4 md:px-6">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Step {{ index + 1 }} of {{ scenes.length }}
          </p>
          <div class="h-1 w-32 overflow-hidden rounded-full bg-secondary" aria-hidden="true">
            <div class="h-full bg-primary" :style="{ width: `${progress * 100}%` }" />
          </div>
        </div>
        <div :aria-live="playing ? 'off' : 'polite'">
          <h3 class="mt-2 text-lg font-semibold text-foreground md:text-xl" data-testid="story-title">{{ scene.title }}</h3>
          <p class="mt-1.5 text-sm leading-relaxed text-muted-foreground md:text-base">{{ scene.body }}</p>
          <p class="mt-2 text-sm font-medium text-foreground">
            <span class="text-primary">Why it matters:</span> {{ scene.why }}
          </p>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" class="ctl" :disabled="index === 0" aria-label="Previous step" @click="go(index - 1)">
            <ChevronLeft class="h-4 w-4" />
          </button>
          <button
            type="button"
            class="ctl ctl--primary"
            :aria-label="playing ? 'Pause' : atEnd && progress >= 1 ? 'Replay' : 'Play'"
            data-testid="story-play"
            @click="playing ? pause() : play()"
          >
            <Pause v-if="playing" class="h-4 w-4" />
            <RotateCcw v-else-if="atEnd && progress >= 1" class="h-4 w-4" />
            <Play v-else class="h-4 w-4" />
            <span class="text-sm">{{ playing ? 'Pause' : atEnd && progress >= 1 ? 'Replay' : 'Play' }}</span>
          </button>
          <button type="button" class="ctl" :disabled="atEnd" aria-label="Next step" @click="go(index + 1)">
            <ChevronRight class="h-4 w-4" />
          </button>
          <!-- The visible dot stays small; the button around it is 32px tall and at least 24px wide,
               so it can be hit with a thumb. -->
          <div class="ml-auto flex" role="tablist" aria-label="Steps">
            <button
              v-for="(s, i) in scenes"
              :key="s.id"
              type="button"
              role="tab"
              :aria-selected="i === index"
              :aria-label="`Step ${i + 1}: ${s.title}`"
              :data-testid="`story-step-${i + 1}`"
              class="group flex h-8 min-w-6 items-center justify-center px-1"
              @click="go(i)"
            >
              <span
                class="block h-2.5 rounded-full transition-all"
                :class="i === index ? 'w-6 bg-primary' : 'w-2.5 bg-border group-hover:bg-muted-foreground'"
              />
            </button>
          </div>
        </div>
      </div>
    </div>

    <ol v-if="!compact" class="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <li v-for="(s, i) in scenes" :key="s.id">
        <button
          type="button"
          class="w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors"
          :class="i === index ? 'border-primary bg-primary/5 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'"
          @click="go(i)"
        >
          <span class="mr-1 font-semibold text-primary">{{ i + 1 }}.</span>{{ s.title }}
        </button>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.story:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 4px;
  border-radius: 1rem;
}

/* ---- stage parts ---- */
.panel { fill: var(--background); stroke: var(--border); stroke-width: 1.5; transition: opacity 0.6s; }
.panel--dim { opacity: 0.45; }
.panel-bar { fill: var(--secondary); }
.dot { fill: var(--border); }
.wire { stroke: var(--border); stroke-width: 2; stroke-dasharray: 6 6; }
.fill-muted { fill: var(--border); }
.label { fill: var(--muted-foreground); font-size: 13px; font-family: inherit; }
.tiny { fill: var(--muted-foreground); font-size: 11px; font-family: inherit; }
.strong { fill: var(--foreground); font-weight: 600; }
.bad { fill: var(--destructive); }

.doc { fill: var(--card); stroke: var(--border); stroke-width: 1.5; transition: fill 0.6s, stroke 0.6s; }
.doc--cipher { fill: color-mix(in oklab, var(--primary) 10%, var(--card)); stroke: color-mix(in oklab, var(--primary) 50%, var(--border)); }
.doc--tampered { stroke: var(--destructive); stroke-width: 2.5; }
.doc--refused { stroke: color-mix(in oklab, var(--destructive) 60%, var(--border)); }
.ink { fill: var(--border); }
.strong-ink { fill: var(--muted-foreground); }
.hex { fill: var(--primary); font: 600 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
.hex.small { font-size: 11px; }
.hex--bad { fill: var(--destructive); }

.badge { fill: var(--primary); }
.badge-ink { fill: var(--primary-foreground); }
.badge-stroke { fill: none; stroke: var(--primary-foreground); stroke-width: 2; }

.key-bg { fill: color-mix(in oklab, #f59e0b 18%, var(--card)); stroke: #f59e0b; stroke-width: 1.5; }
.key { fill: none; stroke: #d97706; stroke-width: 3; }
.key-stroke { fill: none; stroke: #d97706; stroke-width: 3; stroke-linecap: round; }

.env { stroke-width: 1.5; }
.env--alice { fill: color-mix(in oklab, var(--primary) 18%, var(--card)); stroke: var(--primary); }
.env--recovery { fill: var(--card); stroke: var(--muted-foreground); stroke-dasharray: 3 3; }
.env--bob { fill: color-mix(in oklab, #8b5cf6 20%, var(--card)); stroke: #8b5cf6; }
.env-flap { fill: none; stroke: var(--muted-foreground); stroke-width: 1.2; }

.db { fill: var(--secondary); stroke: var(--border); stroke-width: 1.5; }
.db-line { fill: none; stroke: var(--border); stroke-width: 1.5; }

.intruder { fill: var(--muted-foreground); opacity: 0.85; }
.intruder-mask { fill: var(--background); }
.bubble { fill: var(--card); stroke: var(--border); }

.field { fill: var(--card); stroke: var(--border); }
.ok { fill: var(--success); }
.ok-stroke { fill: none; stroke: #fff; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.ok-text { fill: var(--success); font-weight: 600; }
.bad-bg { fill: color-mix(in oklab, var(--destructive) 15%, var(--card)); stroke: var(--destructive); stroke-width: 2; }
.bad-stroke { fill: none; stroke: var(--destructive); stroke-width: 4; stroke-linecap: round; }

/* ---- motion ---- */
.fade { transition: opacity 0.7s ease; }
.pop { transition: opacity 0.5s ease, transform 0.5s ease; }
.is-hidden { opacity: 0; pointer-events: none; }

.packet { animation-duration: 1.6s; animation-timing-function: ease-in-out; animation-fill-mode: both; animation-delay: 0.4s; }
.packet--to-server { animation-name: to-server; }
.packet--to-bob { animation-name: to-bob; }
@keyframes to-server {
  0% { transform: translateX(0); opacity: 0; }
  10% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(120px); opacity: 0; }
}
@keyframes to-bob {
  0% { transform: translateX(0); opacity: 0; }
  10% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(110px); opacity: 0; }
}

.story--still .fade,
.story--still .pop,
.story--still .panel,
.story--still .doc { transition: none; }
.story--still .packet { animation: none; opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .fade, .pop, .panel, .doc { transition: none; }
  .packet { animation: none; opacity: 0; }
}

/* ---- controls ---- */
.ctl {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  height: 2.25rem;
  min-width: 2.25rem;
  justify-content: center;
  border-radius: 9999px;
  border: 1px solid var(--border);
  padding: 0 0.75rem;
  color: var(--foreground);
  transition: background-color 0.2s;
}
.ctl:hover:not(:disabled) { background: var(--secondary); }
.ctl:disabled { opacity: 0.4; }
.ctl--primary { background: var(--primary); border-color: var(--primary); color: var(--primary-foreground); }
.ctl--primary:hover:not(:disabled) { background: color-mix(in oklab, var(--primary) 88%, black); }
</style>
