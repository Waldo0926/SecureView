<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { BookOpen, FlaskConical, GraduationCap, Layers } from 'lucide-vue-next'
import PageHeader from '@/components/securfile/PageHeader.vue'
import AlgorithmExplorer from '@/components/education/AlgorithmExplorer.vue'
import CryptoPlayground from '@/components/education/CryptoPlayground.vue'
import KnowledgeSearch from '@/components/education/KnowledgeSearch.vue'

type SectionId = 'algorithms' | 'playground' | 'knowledge'

const route = useRoute()
const activeSection = ref<SectionId>('algorithms')

// Deep links from the Help assistant: `?article=<id>` opens the Knowledge Base on that article,
// `?algorithm=<id>` the Algorithm Explorer on that algorithm. The sections read the id themselves.
watch(
  () => [route.query.article, route.query.algorithm],
  ([article, algorithm]) => {
    if (typeof article === 'string') activeSection.value = 'knowledge'
    else if (typeof algorithm === 'string') activeSection.value = 'algorithms'
  },
  { immediate: true },
)

const sections: { id: SectionId; label: string; description: string; icon: typeof Layers }[] = [
  {
    id: 'algorithms',
    label: 'Algorithm Explorer',
    description: 'Learn AES-128, AES-256, RSA, SHA, ChaCha20, and Argon2id with animated demos.',
    icon: Layers,
  },
  {
    id: 'playground',
    label: 'Playground',
    description: 'Try Caesar, Vigenère, Rail Fence, AES, and RSA interactively in your browser.',
    icon: FlaskConical,
  },
  {
    id: 'knowledge',
    label: 'Knowledge Base',
    description: 'Search articles on encryption basics, keys, and best practices.',
    icon: BookOpen,
  },
]
</script>

<template>
  <section class="product-page">
    <div class="page-container">
      <PageHeader
        eyebrow="Encryption Education"
        title="Learn How Encryption Works"
        subtitle="Explore algorithms, try hands-on demos, and search the knowledge library."
      />

      <div class="mb-10">
        <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <button
            v-for="section in sections"
            :key="section.id"
            type="button"
            class="rounded-xl border p-4 text-left transition-all"
            :class="
              activeSection === section.id
                ? 'border-primary bg-primary/10 shadow-sm'
                : 'border-border bg-card hover:border-primary/30'
            "
            @click="activeSection = section.id"
          >
            <component
              :is="section.icon"
              class="h-5 w-5 mb-2"
              :class="activeSection === section.id ? 'text-primary' : 'text-muted-foreground'"
            />
            <p class="font-semibold text-foreground">{{ section.label }}</p>
            <p class="text-sm text-muted-foreground mt-1 leading-relaxed">{{ section.description }}</p>
          </button>
        </div>
      </div>

      <div>
        <AlgorithmExplorer v-if="activeSection === 'algorithms'" />
        <CryptoPlayground v-else-if="activeSection === 'playground'" />
        <KnowledgeSearch v-else-if="activeSection === 'knowledge'" />
      </div>
    </div>
  </section>
</template>
