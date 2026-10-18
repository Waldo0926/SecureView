<script setup lang="ts">
import FileEncryption from '@/components/securfile/file-encryption.vue'
import PageHeader from '@/components/securfile/PageHeader.vue'
import SecurityStory from '@/components/explainers/SecurityStory.vue'
</script>

<template>
  <FileEncryption />
  <!-- Explain the file lifecycle below the upload controls. -->
  <section id="security-story" class="py-20" aria-labelledby="story-heading">
    <div class="page-container">
      <PageHeader
        as="h2"
        title-id="story-heading"
        eyebrow="Under the hood"
        title="What happens to your file"
        subtitle="Encrypted in your browser, stored as noise, shared by re-sealing a key, and checked on the way out."
      />
      <SecurityStory compact />
    </div>
  </section>


</template>
