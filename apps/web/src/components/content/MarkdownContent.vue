<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, watch } from 'vue'

interface MarkdownHeading {
  id: string
  level: number
  text: string
}

const props = withDefaults(defineProps<{ content: string; headingPrefix?: string }>(), {
  headingPrefix: 'section',
})
const emit = defineEmits<{ headings: [headings: MarkdownHeading[]] }>()

const rendered = computed(() => {
  const parsed = marked.parse(props.content, {
    async: false,
    breaks: false,
    gfm: true,
  })

  const sanitized = DOMPurify.sanitize(parsed, {
    FORBID_ATTR: ['style'],
    FORBID_TAGS: ['style'],
    USE_PROFILES: { html: true },
  })
  const parsedDocument = new DOMParser().parseFromString(`<div>${sanitized}</div>`, 'text/html')
  const container = parsedDocument.body.firstElementChild as HTMLElement
  const usedSlugs = new Map<string, number>()
  const headings = Array.from(container.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')).map(
    heading => {
      const baseSlug = slugify(heading.textContent ?? '') || 'section'
      const occurrence = usedSlugs.get(baseSlug) ?? 0
      usedSlugs.set(baseSlug, occurrence + 1)
      const slug = occurrence === 0 ? baseSlug : `${baseSlug}-${occurrence + 1}`
      const id = `${props.headingPrefix}-${slug}`
      heading.id = id
      return { id, level: Number(heading.tagName.slice(1)), text: heading.textContent?.trim() || 'Section' }
    },
  )

  return { content: container.innerHTML, headings }
})

watch(
  () => rendered.value.headings,
  headings => emit('headings', headings),
  { immediate: true },
)

function slugify(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
</script>

<template>
  <!-- The parser output is sanitized immediately above before it reaches the DOM. -->
  <div class="markdown-content" v-html="rendered.content" />
</template>
