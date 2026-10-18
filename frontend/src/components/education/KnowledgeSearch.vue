<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { BookOpen, Search, Tag } from 'lucide-vue-next'
import {
  categoryLabels,
  knowledgeArticles,
  searchKnowledge,
  type KnowledgeCategory,
} from '@/data/education/knowledge'
import { renderKnowledgeContent } from '@/utils/render-knowledge-content'
import { translateSource } from '@/i18n'

const query = ref('')
const category = ref<KnowledgeCategory | 'all'>('all')
const expandedId = ref<string | null>(knowledgeArticles[0]?.id ?? null)

const categories = computed(() => [
  { id: 'all' as const, label: 'All Topics', count: knowledgeArticles.length },
  ...Object.entries(categoryLabels).map(([id, label]) => ({
    id: id as KnowledgeCategory,
    label,
    count: knowledgeArticles.filter((a) => a.category === id).length,
  })),
])

const results = computed(() => searchKnowledge(query.value, category.value))

// `/education?article=<id>#article-<id>` opens that article, which is how the Help assistant
// links to one; the router's hash scrolling then brings it into view.
const route = useRoute()
watch(
  () => route.query.article,
  (id) => {
    if (typeof id !== 'string' || !knowledgeArticles.some((a) => a.id === id)) return
    query.value = ''
    category.value = 'all'
    expandedId.value = id
  },
  { immediate: true },
)

function toggle(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function renderedContent(content: string) {
  // Chinese is swapped in as whole Markdown, before rendering (Issue #74).
  return renderKnowledgeContent(translateSource(content))
}
</script>

<template>
  <div class="grid lg:grid-cols-[220px_1fr] gap-6">
    <aside class="space-y-4">
      <div class="relative">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          v-model="query"
          type="search"
          placeholder="Search knowledge..."
          class="w-full h-10 pl-9 pr-3 rounded-md border border-border bg-card text-sm"
        />
      </div>

      <div class="rounded-xl border border-border bg-card p-3 space-y-1">
        <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide px-2 py-1">Categories</p>
        <button
          v-for="cat in categories"
          :key="cat.id"
          type="button"
          class="w-full text-left rounded-md px-3 py-2 text-sm transition-colors flex items-center justify-between"
          :class="
            category === cat.id
              ? 'bg-primary/10 text-foreground font-medium'
              : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
          "
          @click="category = cat.id"
        >
          <span>{{ cat.label }}</span>
          <span class="text-xs opacity-70">{{ cat.count }}</span>
        </button>
      </div>
    </aside>

    <div class="space-y-3">
      <p class="text-sm text-muted-foreground">
        {{ results.length }} article{{ results.length === 1 ? '' : 's' }} found
        <span v-if="query"> for "{{ query }}"</span>
      </p>

      <article
        v-for="article in results"
        :id="`article-${article.id}`"
        :key="article.id"
        class="scroll-mt-24 rounded-xl border border-border bg-card overflow-hidden transition-shadow hover:shadow-sm"
      >
        <button
          type="button"
          class="w-full text-left px-5 py-4 flex items-start gap-3"
          @click="toggle(article.id)"
        >
          <div class="p-2 rounded-lg bg-primary/10 flex-shrink-0 mt-0.5">
            <BookOpen class="h-4 w-4 text-primary" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex flex-wrap items-center gap-2 mb-1">
              <h4 class="font-semibold text-foreground">{{ article.title }}</h4>
              <span class="text-[10px] font-medium uppercase tracking-wide text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                {{ categoryLabels[article.category] }}
              </span>
            </div>
            <p class="text-sm text-muted-foreground">{{ article.summary }}</p>
            <div class="flex flex-wrap gap-1.5 mt-2">
              <span
                v-for="tag in article.tags.slice(0, 4)"
                :key="tag"
                class="inline-flex items-center gap-1 text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded-full"
              >
                <Tag class="h-2.5 w-2.5" />
                {{ tag }}
              </span>
            </div>
          </div>
        </button>

        <div
          v-if="expandedId === article.id"
          class="px-5 pb-6 pt-0 border-t border-border mx-5"
        >
          <div
            class="knowledge-content pt-5"
            v-html="renderedContent(article.content)"
          />
        </div>
      </article>

      <div v-if="results.length === 0" class="rounded-xl border border-dashed border-border p-12 text-center">
        <Search class="h-8 w-8 text-muted-foreground mx-auto mb-3 opacity-50" />
        <p class="text-foreground font-medium">No articles found</p>
        <p class="text-sm text-muted-foreground mt-1">Try different keywords like "AES", "public key", or "hash".</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge-content :deep(strong) {
  font-weight: 600;
  color: var(--foreground);
}

.knowledge-content :deep(em) {
  font-style: italic;
}

.knowledge-content :deep(p + ul),
.knowledge-content :deep(p + ol),
.knowledge-content :deep(ul + p),
.knowledge-content :deep(ol + p) {
  margin-top: 0.75rem;
}
</style>
