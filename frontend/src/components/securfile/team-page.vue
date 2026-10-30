<script setup lang="ts">
import PageHeader from '@/components/securfile/PageHeader.vue'
import { ArrowUpRight, Bug, Code, Github, GraduationCap, Lightbulb, LockKeyhole, Mail, Maximize2, MessageSquare, Palette, Send, Server, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Component } from 'vue'
import asadPhoto from '@/assets/people/asad-malik.jpg'
import jasonPhoto from '@/assets/people/jason-huang.jpg'
import junyanPhoto from '@/assets/people/junyan-li.jpg'
import shuoxunPhoto from '@/assets/people/shuoxun-wen.jpg'
import taiPhoto from '@/assets/people/tai-chen.jpg'

/**
 * Contact us: feedback, then the supervisor and the development team as tilted sticker tiles.
 *
 * The tile design is Junyan Li's and is kept as it was. What changed is the information on it:
 * names, roles and one-line responsibilities follow the group's MCS21 presentation, each member
 * links their GitHub profile and Monash student email, and every tile has a photo in a large
 * sticker centred in the left column. The supervisor's tile also carries the title, research
 * interests and profile link from his Monash research profile.
 */

const SUPERVISOR_PROFILE_URL = 'https://research.monash.edu/en/persons/asad-malik/'

interface TeamMember {
  name: string
  role: string
  icon: Component
  initials: string
  bio: string
  detail: string
  accent: string
  stickerTone: string
  /** Everyone has a photo, shown in the large sticker. Only the supervisor has a profile link. */
  photo?: string
  title?: string
  affiliation?: string
  interests?: string[]
  profileUrl?: string
  github?: { url: string; handle: string }
  email?: string
}

const members: TeamMember[] = [
  {
    name: 'Dr. Asad Malik',
    role: 'Project supervisor',
    icon: GraduationCap,
    initials: 'AM',
    bio: 'Lecturer and Cybersecurity Group Leader, School of Information Technology, Monash University Malaysia.',
    detail:
      'Guides SecureView on scope, technical direction and evaluation, so the team keeps a coherent security architecture, realistic milestones and a platform that stands up to review.',
    accent: 'from-amber-500/20 via-transparent to-amber-500/5',
    stickerTone: 'sticker-amber',
    photo: asadPhoto,
    title: 'Lecturer and Cybersecurity Group Leader',
    affiliation: 'School of Information Technology, Monash University Malaysia',
    interests: ['Cybersecurity', 'Multimedia forensics', 'DeepFake detection', 'Trustworthy AI'],
    profileUrl: SUPERVISOR_PROFILE_URL,
  },
  {
    name: 'Shuoxun Wen',
    role: 'Project Lead',
    icon: Palette,
    initials: 'SW',
    bio: 'Backlog, server and deployment, MySQL, testing and documentation.',
    detail:
      'Runs the backlog and the release process, owns the staging server and its deployment, the MySQL database, and the testing and documentation that show the platform does what it claims.',
    accent: 'from-foreground/5 via-transparent to-transparent',
    stickerTone: 'sticker-blue',
    photo: shuoxunPhoto,
    github: { url: 'https://github.com/Waldo0926', handle: 'Waldo0926' },
    email: 'swen0027@student.monash.edu',
  },
  {
    name: 'Junyan Li',
    role: 'Frontend and Interface',
    icon: Code,
    initials: 'JL',
    bio: 'Vue pages, product journeys, Education and Help content.',
    detail:
      'Builds the SecureView interface: the Vue pages, the product journeys, and the Education and Help content, so security features stay readable and approachable on every screen size.',
    accent: 'from-sky-500/20 via-transparent to-sky-500/5',
    stickerTone: 'sticker-sky',
    photo: junyanPhoto,
    github: { url: 'https://github.com/jlii0421', handle: 'jlii0421' },
    email: 'jlii0421@student.monash.edu',
  },
  {
    name: 'Jason Huang',
    role: 'Backend and APIs',
    icon: Server,
    initials: 'JH',
    bio: 'FastAPI services, authentication, sharing and audit endpoints.',
    detail:
      'Maintains the FastAPI services behind the platform: authentication, file storage, sharing and the audit endpoints, so encrypted collaboration has a dependable server backbone.',
    accent: 'from-slate-500/20 via-transparent to-slate-500/5',
    stickerTone: 'sticker-slate',
    photo: jasonPhoto,
    github: { url: 'https://github.com/jsonrar', handle: 'jsonrar' },
    email: 'jhua0176@student.monash.edu',
  },
  {
    name: 'Tai Chen',
    role: 'Cryptography',
    icon: LockKeyhole,
    initials: 'TC',
    bio: 'Browser encryption, file envelope, key wrapping and test vectors.',
    detail:
      'Implements the browser-side cryptography, the encrypted file envelope and key wrapping, and the test vectors that check them, so plaintext never needs to leave the client trust boundary.',
    accent: 'from-emerald-500/20 via-transparent to-emerald-500/5',
    stickerTone: 'sticker-emerald',
    photo: taiPhoto,
    github: { url: 'https://github.com/Charter888', handle: 'Charter888' },
    email: 'tche0186@student.monash.edu',
  },
]

const supervisor = members.find((member) => member.profileUrl)!
/** The supervisor is one wide tile because it carries more to say; the four members are equal tiles. */
const groups = [
  { key: 'supervisor', class: 'team-supervisor-row', items: [supervisor] },
  { key: 'team', class: 'team-mosaic', items: members.filter((member) => member !== supervisor) },
]

const topics = [
  { icon: MessageSquare, label: 'General feedback', hint: 'What worked and what did not' },
  { icon: Lightbulb, label: 'Feature suggestion', hint: 'What you would like next' },
  { icon: Bug, label: 'Bug report', hint: 'Something that broke or looked wrong' },
]

/** Demo-only contact form — nothing is sent to a server yet. */
const feedbackName = ref('')
const feedbackEmail = ref('')
const feedbackTopic = ref('feedback')
const feedbackMessage = ref('')
/** Where feedback goes: the project lead, whose address is also on his card below. */
const FEEDBACK_ADDRESS = 'swen0027@student.monash.edu'
const feedbackSubmitted = ref(false)
const feedbackError = ref('')

function submitFeedback() {
  feedbackError.value = ''
  if (!feedbackName.value.trim() || !feedbackEmail.value.trim() || !feedbackMessage.value.trim()) {
    feedbackError.value = 'Please fill in your name, email, and message.'
    return
  }
  // There is no feedback inbox on the server, so the form hands the note to the visitor's own
  // email app, addressed to the team. It used to pretend the note had been received.
  const topics: Record<string, string> = {
    feedback: 'General feedback',
    suggestion: 'Feature suggestion',
    bug: 'Bug report',
    other: 'Other',
  }
  const subject = `[SecureView] ${topics[feedbackTopic.value] ?? 'Feedback'} from ${feedbackName.value.trim()}`
  const body = `${feedbackMessage.value.trim()}\n\n— ${feedbackName.value.trim()} <${feedbackEmail.value.trim()}>`
  window.location.href =
    `mailto:${FEEDBACK_ADDRESS}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
  feedbackSubmitted.value = true
}

function resetFeedback() {
  feedbackName.value = ''
  feedbackEmail.value = ''
  feedbackTopic.value = 'feedback'
  feedbackMessage.value = ''
  feedbackSubmitted.value = false
  feedbackError.value = ''
}

const fieldClass =
  'h-11 w-full rounded-xl border border-border bg-background px-4 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary'

/** Which profile is enlarged. Opened by a click, tap or Enter, closed by Esc, the X or a click outside. */
const activeId = ref<string | null>(null)
const activeMember = computed(() => members.find((m) => m.name === activeId.value) ?? null)

function openProfile(name: string) {
  activeId.value = name
}

function dismissOverlay() {
  activeId.value = null
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') dismissOverlay()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <section class="relative overflow-hidden py-14 md:py-20">

    <div class="page-container">
      <PageHeader
        eyebrow="SecureView"
        title="Contact us"
        subtitle="Send us feedback, then meet the supervisor and the team behind SecureView."
      />

      <!-- Feedback: the pitch on the left, the form on the right, so a wide screen is used and not left half empty. -->
      <div class="mb-16 grid gap-8 md:mb-20 lg:grid-cols-5 lg:gap-12" data-testid="team-feedback">
        <div class="lg:col-span-2">
          <p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">Feedback</p>
          <h2 class="mt-2 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            Share a note with the team
          </h2>
          <p class="mt-3 text-sm text-muted-foreground md:text-base">
            Tell us what worked, what did not, or what you would like next. Sending opens your own email
            app with the note ready to go to the team.
          </p>
          <ul class="mt-6 space-y-3">
            <li v-for="topic in topics" :key="topic.label" class="flex items-start gap-3">
              <span class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <component :is="topic.icon" class="h-4 w-4" />
              </span>
              <span>
                <span class="block text-sm font-medium text-foreground">{{ topic.label }}</span>
                <span class="block text-sm text-muted-foreground">{{ topic.hint }}</span>
              </span>
            </li>
          </ul>
        </div>

        <div class="rounded-3xl border border-border bg-card p-6 shadow-sm md:p-8 lg:col-span-3">
          <div
            v-if="feedbackSubmitted"
            class="rounded-2xl border border-primary/25 bg-primary/10 px-5 py-6"
            role="status"
          >
            <p class="text-base font-medium text-foreground">Your email app should now be open.</p>
            <p class="mt-2 text-sm text-muted-foreground">
              The note is ready to send to the team. Press Send there to deliver it. If no email app
              opened, write to <a :href="`mailto:${FEEDBACK_ADDRESS}`" class="text-primary hover:underline">{{ FEEDBACK_ADDRESS }}</a>.
            </p>
            <button
              type="button"
              class="mt-5 inline-flex h-11 items-center rounded-full border border-border bg-card px-5 text-sm text-foreground transition-colors hover:bg-secondary"
              @click="resetFeedback"
            >
              Write another note
            </button>
          </div>

          <form v-else class="space-y-5" @submit.prevent="submitFeedback">
            <div class="grid gap-5 sm:grid-cols-2">
              <label class="block space-y-2">
                <span class="text-sm font-medium text-foreground">Name</span>
                <input v-model="feedbackName" type="text" autocomplete="name" placeholder="Your name" :class="fieldClass" />
              </label>
              <label class="block space-y-2">
                <span class="text-sm font-medium text-foreground">Email</span>
                <input v-model="feedbackEmail" type="email" autocomplete="email" placeholder="you@example.com" :class="fieldClass" />
              </label>
            </div>

            <label class="block space-y-2">
              <span class="text-sm font-medium text-foreground">Topic</span>
              <select v-model="feedbackTopic" :class="fieldClass">
                <option value="feedback">General feedback</option>
                <option value="suggestion">Feature suggestion</option>
                <option value="bug">Bug report</option>
                <option value="other">Other</option>
              </select>
            </label>

            <label class="block space-y-2">
              <span class="text-sm font-medium text-foreground">Message</span>
              <textarea
                v-model="feedbackMessage"
                rows="5"
                placeholder="Tell us what worked, what did not, or what you would like next…"
                class="w-full resize-y rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
              />
            </label>

            <p v-if="feedbackError" class="text-sm text-destructive" role="alert">{{ feedbackError }}</p>

            <button
              type="submit"
              class="inline-flex h-11 items-center gap-2 rounded-full bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Send class="h-4 w-4" />
              Write the email
            </button>
          </form>
        </div>
      </div>

      <div class="mb-8 max-w-3xl md:mb-10">
        <p class="mb-2 text-xs uppercase font-mono tracking-[0.14em] text-muted-foreground">Supervisor and development team · Group MCS21</p>
        <h2 class="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          The people behind
          <span class="text-primary">SecureView</span>
        </h2>
        <p class="mt-3 max-w-2xl text-base text-muted-foreground md:text-lg">
          SecureView is supervised by Dr. Asad Malik and built by four Monash students. Each of them owns an area of the platform, from the browser-side encryption to the server and its tests.
        </p>
      </div>

      <div data-testid="team-members" class="team-groups">
        <div
          v-for="group in groups"
          :key="group.key"
          :class="group.class"
        >
          <article
            v-for="member in group.items"
            :key="member.name"
            class="team-tile group"
            :data-testid="member.profileUrl ? 'team-supervisor' : 'team-member'"
            tabindex="0"
            :aria-label="`${member.name}: open the full profile`"
            aria-haspopup="dialog"
            @click="openProfile(member.name)"
            @keydown.enter.prevent="openProfile(member.name)"
            @keydown.space.prevent="openProfile(member.name)"
          >
            <div class="team-tile__frame" :class="`bg-gradient-to-br ${member.accent}`">
              <div class="team-tile__split" :class="{ 'team-tile__split--supervisor': member.profileUrl }">
                <div class="team-tile__identity">
                  <div class="team-sticker" :class="[member.stickerTone, { 'team-sticker--lg': member.photo }]">
                    <img
                      v-if="member.photo"
                      :src="member.photo"
                      :alt="`Portrait of ${member.name}`"
                      width="640"
                      :height="member.profileUrl ? 789 : 640"
                      class="team-sticker__photo"
                      loading="lazy"
                    />
                    <span v-else class="team-sticker__initials">{{ member.initials }}</span>
                    <span class="team-sticker__tape" aria-hidden="true" />
                    <span class="team-sticker__badge">
                      <component :is="member.icon" class="h-4 w-4" />
                    </span>
                  </div>
                  <h3 class="mt-4 whitespace-nowrap text-xl font-semibold tracking-tight text-foreground md:text-2xl">
                    {{ member.name }}
                  </h3>
                  <p class="mt-1 text-sm font-medium text-primary">{{ member.role }}</p>
                </div>

                <div class="team-tile__bio">
                  <template v-if="member.profileUrl">
                    <p class="text-base font-semibold leading-snug text-foreground">{{ member.title }}</p>
                    <p class="mt-1 text-sm text-muted-foreground">{{ member.affiliation }}</p>
                    <p class="mt-4 text-sm leading-relaxed text-foreground">{{ member.detail }}</p>
                    <p class="mt-4 text-[0.7rem] font-semibold uppercase tracking-[0.2em] text-muted-foreground">Research interests</p>
                    <ul class="mt-2 flex flex-wrap gap-2">
                      <li
                        v-for="interest in member.interests"
                        :key="interest"
                        class="rounded-full border border-border bg-secondary/60 px-3 py-1 text-xs text-foreground"
                      >
                        {{ interest }}
                      </li>
                    </ul>
                  </template>
                  <template v-else>
                    <p class="text-base font-semibold leading-snug text-foreground">{{ member.bio }}</p>
                    <p class="mt-3 text-sm leading-relaxed text-muted-foreground">{{ member.detail }}</p>
                  </template>

                  <div class="team-links" @click.stop @keydown.enter.stop @keydown.space.stop>
                    <a
                      v-if="member.profileUrl"
                      :href="member.profileUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="team-link team-link--button"
                      data-testid="supervisor-profile-link"
                    >
                      <ArrowUpRight class="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span>View Monash profile</span>
                    </a>
                    <template v-else>
                      <a
                        :href="member.github!.url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="team-link"
                        :aria-label="`${member.name} on GitHub`"
                        data-testid="member-github"
                      >
                        <Github class="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span>@{{ member.github!.handle }}</span>
                      </a>
                      <a
                        :href="`mailto:${member.email}`"
                        class="team-link"
                        :aria-label="`Email ${member.name}`"
                        data-testid="member-email"
                      >
                        <Mail class="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span>{{ member.email!.split('@')[0] }}@<wbr />{{ member.email!.split('@')[1] }}</span>
                      </a>
                    </template>
                  </div>
                  <p class="team-hint">
                    <Maximize2 class="h-3.5 w-3.5" aria-hidden="true" />
                    Click or tap to enlarge
                  </p>
                </div>
              </div>
            </div>
          </article>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <Transition name="team-overlay">
        <div
          v-if="activeMember"
          class="team-overlay"
          role="dialog"
          aria-modal="true"
          :aria-label="`${activeMember.name} profile`"
          @click.self="dismissOverlay"
        >
          <div class="team-popup">
            <button
              type="button"
              class="team-popup__close"
              aria-label="Close profile"
              @click="dismissOverlay"
            >
              <X class="h-4 w-4" />
            </button>

            <div class="team-profile">
              <div
                class="team-profile__media"
                :class="[activeMember.stickerTone, { 'team-profile__media--member': !activeMember.profileUrl }]"
              >
                <img
                  v-if="activeMember.photo"
                  :src="activeMember.photo"
                  :alt="`Portrait of ${activeMember.name}`"
                  class="team-profile__photo"
                />
                <span v-else class="team-profile__initials">{{ activeMember.initials }}</span>
              </div>

              <div class="team-profile__body">
                <span class="inline-flex w-fit items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  <component :is="activeMember.icon" class="h-3.5 w-3.5" />
                  {{ activeMember.role }}
                </span>
                <h2 class="mt-4 text-3xl font-bold tracking-tight text-foreground md:text-5xl">
                  {{ activeMember.name }}
                </h2>
                <template v-if="activeMember.profileUrl">
                  <p class="mt-2 text-lg font-medium text-primary md:text-xl">{{ activeMember.title }}</p>
                  <p class="text-sm text-muted-foreground md:text-base">{{ activeMember.affiliation }}</p>
                </template>
                <p v-else class="mt-2 text-lg font-medium text-primary md:text-xl">{{ activeMember.bio }}</p>

                <p class="mt-5 text-base leading-relaxed text-foreground md:text-lg">
                  {{ activeMember.detail }}
                </p>

                <template v-if="activeMember.interests">
                  <p class="mt-6 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Research interests</p>
                  <ul class="mt-2 flex flex-wrap gap-2">
                    <li
                      v-for="interest in activeMember.interests"
                      :key="interest"
                      class="rounded-full border border-border bg-secondary/60 px-4 py-1.5 text-sm text-foreground md:text-base"
                    >
                      {{ interest }}
                    </li>
                  </ul>
                </template>

                <div class="team-popup__links">
                  <a
                    v-if="activeMember.profileUrl"
                    :href="activeMember.profileUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="team-link team-link--button"
                  >
                    <ArrowUpRight class="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span>View Monash profile</span>
                  </a>
                  <template v-else-if="activeMember.github">
                    <a :href="activeMember.github.url" target="_blank" rel="noopener noreferrer" class="team-link team-link--button">
                      <Github class="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span>@{{ activeMember.github.handle }}</span>
                    </a>
                    <a :href="`mailto:${activeMember.email}`" class="team-link team-link--button">
                      <Mail class="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span>{{ activeMember.email!.split('@')[0] }}@<wbr />{{ activeMember.email!.split('@')[1] }}</span>
                    </a>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<style scoped>
.team-groups {
  display: grid;
  gap: 1.15rem;
}

.team-supervisor-row,
.team-mosaic {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.15rem;
}

.team-tile {
  position: relative;
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), z-index 0s;
  cursor: pointer;
  outline: none;
}

.team-tile:hover,
.team-tile:focus-visible {
  z-index: 3;
  transform: translateY(-4px) scale(1.015);
}

.team-tile__frame {
  height: 100%;
  min-height: 14rem;
  border: 1px solid var(--border);
  border-radius: 1.25rem;
  background: color-mix(in oklab, var(--card) 94%, transparent);
  backdrop-filter: blur(12px);
  box-shadow: 0 18px 40px color-mix(in oklab, var(--foreground) 7%, transparent);
  overflow: hidden;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.team-tile:hover .team-tile__frame,
.team-tile:focus-visible .team-tile__frame {
  border-color: color-mix(in oklab, var(--primary) 42%, var(--border));
  box-shadow: 0 26px 56px color-mix(in oklab, var(--foreground) 12%, transparent);
}

.team-tile__split {
  display: grid;
  grid-template-columns: minmax(9rem, 0.9fr) minmax(0, 1.1fr);
  height: 100%;
  min-height: inherit;
}

.team-tile__identity {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 1.25rem 1.1rem 1.25rem 1.25rem;
  border-right: 1px dashed color-mix(in oklab, var(--border) 85%, var(--primary));
  background: color-mix(in oklab, var(--secondary) 55%, transparent);
}

.team-tile__bio {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding: 1.25rem 1.35rem;
}

.team-sticker {
  position: relative;
  width: 5.5rem;
  height: 6.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.85rem;
  border: 1px solid color-mix(in oklab, var(--border) 70%, transparent);
  background:
    linear-gradient(145deg, color-mix(in oklab, white 18%, transparent), transparent 55%),
    color-mix(in oklab, var(--card) 88%, var(--primary));
  box-shadow:
    0 10px 24px color-mix(in oklab, var(--foreground) 10%, transparent),
    inset 0 1px 0 color-mix(in oklab, white 35%, transparent);
  transform: rotate(-4deg);
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

.team-tile:hover .team-sticker,
.team-tile:focus-visible .team-sticker {
  transform: rotate(0deg) scale(1.04);
}

.team-sticker__photo {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  object-fit: cover;
  object-position: top;
}

.team-sticker__tape {
  z-index: 1;
  position: absolute;
  top: -0.45rem;
  left: 50%;
  width: 2.4rem;
  height: 0.7rem;
  transform: translateX(-50%) rotate(-2deg);
  border-radius: 0.15rem;
  background: color-mix(in oklab, var(--primary) 28%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--primary) 18%, transparent);
}

.team-sticker__initials {
  font-size: 1.55rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--foreground);
}

.team-sticker__badge {
  position: absolute;
  right: -0.45rem;
  bottom: -0.45rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.9rem;
  height: 1.9rem;
  border-radius: 999px;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--primary);
  box-shadow: 0 6px 14px color-mix(in oklab, var(--foreground) 10%, transparent);
}

.sticker-blue {
  background:
    linear-gradient(145deg, color-mix(in oklab, white 20%, transparent), transparent 50%),
    var(--card);
}

.sticker-emerald {
  background:
    linear-gradient(145deg, color-mix(in oklab, white 20%, transparent), transparent 50%),
    var(--card);
}

.sticker-sky {
  background:
    linear-gradient(145deg, color-mix(in oklab, white 20%, transparent), transparent 50%),
    var(--card);
}

.sticker-slate {
  background:
    linear-gradient(145deg, color-mix(in oklab, white 20%, transparent), transparent 50%),
    var(--card);
}

.sticker-amber {
  background:
    linear-gradient(145deg, color-mix(in oklab, white 20%, transparent), transparent 50%),
    var(--card);
}

.team-links {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  /* Pinned to the bottom so the links line up from tile to tile whatever the intro length. */
  margin-top: auto;
  padding-top: 0.75rem;
}

.team-link {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 2.5rem;
  width: fit-content;
  max-width: 100%;
  padding: 0 0.4rem;
  border-radius: 0.5rem;
  font-size: 0.8125rem;
  color: var(--foreground);
  overflow-wrap: break-word;
  transition: background 0.2s ease, color 0.2s ease;
}

.team-link:hover {
  background: var(--secondary);
  color: var(--primary);
}

.team-hint {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: color-mix(in oklab, var(--primary) 85%, var(--foreground));
}

.team-sticker--lg {
  width: 8rem;
  height: 9.85rem;
}

.team-tile__split--supervisor {
  grid-template-columns: minmax(11rem, 0.55fr) minmax(0, 1.45fr);
}

.team-link--button {
  min-height: 2.75rem;
  padding: 0 1rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-weight: 500;
}

@media (min-width: 768px) {
  /* Four equal tiles: every row is as tall as the tallest tile in it. */
  .team-mosaic {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-auto-rows: 1fr;
  }

  .team-tile__frame {
    min-height: 15rem;
  }

  .team-tile__identity {
    padding: 1.6rem;
  }

  .team-tile__bio {
    padding: 1.6rem 1.75rem;
  }
}

/* Between 768 and 1023 px the member tiles sit two to a row and the left column is too narrow
   for the large sticker and a name on one line, so the tile is stacked like on a phone. */
@media (min-width: 768px) and (max-width: 1023px) {
  .team-mosaic .team-tile__split {
    grid-template-columns: 1fr;
  }

  .team-mosaic .team-tile__identity {
    border-right: 0;
    border-bottom: 1px dashed color-mix(in oklab, var(--border) 85%, var(--primary));
  }
}

@media (max-width: 639px) {
  .team-tile__split,
  .team-tile__split--supervisor {
    grid-template-columns: 1fr;
  }

  .team-tile__identity {
    border-right: 0;
    border-bottom: 1px dashed color-mix(in oklab, var(--border) 85%, var(--primary));
  }
}

.team-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
  background: color-mix(in oklab, var(--background) 42%, transparent);
  backdrop-filter: blur(10px);
}

.team-popup {
  position: relative;
  width: min(94vw, 70rem);
  max-height: 92vh;
  overflow-y: auto;
  border: 1px solid color-mix(in oklab, var(--primary) 35%, var(--border));
  border-radius: 1.5rem;
  background: var(--card);
  box-shadow: 0 30px 80px color-mix(in oklab, var(--foreground) 18%, transparent);
}

.team-popup__close {
  position: absolute;
  top: 0.9rem;
  right: 0.9rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--muted-foreground);
  transition: background 0.2s ease, color 0.2s ease;
}

.team-popup__close:hover {
  background: var(--secondary);
  color: var(--foreground);
}

/* The enlarged profile: a large portrait that runs the full height of the card, and the whole
   introduction beside it, so enlarging shows clearly more than the tile does. */
.team-profile {
  display: grid;
  grid-template-columns: 1fr;
}

.team-profile__media {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 18rem;
  max-height: 24rem;
  overflow: hidden;
  background: color-mix(in oklab, var(--secondary) 70%, var(--card));
}

.team-profile__photo {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
}

/* The supervisor's portrait is cropped from the top so his face stays in view. The members'
   pictures are square and one of them is a logo with its name under it, so they are cropped
   evenly from the middle instead, and on a phone the box is made square and the whole picture
   is shown, because the short wide box there cut the logo's name in half. */
.team-profile__media--member .team-profile__photo {
  object-position: center;
}

@media (max-width: 767px) {
  .team-profile__media--member {
    width: 100%;
    aspect-ratio: 1;
  }

  .team-profile__media--member .team-profile__photo {
    object-fit: contain;
  }
}

.team-profile__initials {
  font-size: 5rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--foreground);
}

.team-profile__body {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 1.5rem 1.5rem 1.75rem;
}

.team-popup__links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-top: 1.75rem;
}

@media (min-width: 768px) {
  .team-profile {
    grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
    min-height: 30rem;
  }

  .team-profile__media {
    max-height: none;
    min-height: 100%;
  }

  .team-profile__body {
    padding: 2.5rem 3.5rem 2.5rem 2.75rem;
  }
}

.team-overlay-enter-active,
.team-overlay-leave-active {
  transition: opacity 0.28s ease;
}

.team-overlay-enter-active .team-popup,
.team-overlay-leave-active .team-popup {
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.35s ease;
}

.team-overlay-enter-from,
.team-overlay-leave-to {
  opacity: 0;
}

.team-overlay-enter-from .team-popup,
.team-overlay-leave-to .team-popup {
  opacity: 0;
  transform: translateY(18px) scale(0.94);
}

@media (prefers-reduced-motion: reduce) {
  .team-tile,
  .team-sticker,
  .team-tile__frame,
  .team-overlay-enter-active,
  .team-overlay-leave-active,
  .team-overlay-enter-active .team-popup,
  .team-overlay-leave-active .team-popup {
    transition: none;
  }

  .team-tile {
    transform: none;
  }
}
</style>
