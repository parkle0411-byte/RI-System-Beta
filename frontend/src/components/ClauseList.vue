<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps({ clauses: { type: Array, default: () => [] }, sourceLabel: Function, removable: Function })
const emit = defineEmits(['remove'])
const measureElement = ref(null), codeWidth = ref(0), widestLetter = ref('W')
const style = computed(() => codeWidth.value ? { '--clause-code-width': `${codeWidth.value}px` } : {})
let disposed = false, observer
// Measure the actual Code font, weight and letter spacing. `ch` measures zero,
// so it does not represent twenty of the widest uppercase glyphs.
function measure() {
  if (disposed || !measureElement.value) return
  const element = measureElement.value
  let widest = 'A', width = 0
  for (const letter of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') {
    element.textContent = letter
    const measured = element.getBoundingClientRect().width
    if (measured > width) { widest = letter; width = measured }
  }
  element.textContent = widest.repeat(20)
  widestLetter.value = widest
  codeWidth.value = Math.ceil(element.getBoundingClientRect().width)
}
onMounted(async () => {
  await nextTick(); measure()
  observer = new ResizeObserver(() => {
    const width = measureElement.value?.getBoundingClientRect().width || 0
    if (width > 0 && Math.abs(width - codeWidth.value) > 1) measure()
  })
  if (measureElement.value) observer.observe(measureElement.value)
  document.fonts?.ready.then(measure)
  document.fonts?.addEventListener('loadingdone', measure)
})
watch(() => props.clauses.length, async () => { await nextTick(); measure() })
onBeforeUnmount(() => { disposed = true; observer?.disconnect(); document.fonts?.removeEventListener('loadingdone', measure) })
</script>

<template>
  <div class="clause-list" data-testid="clause-list" :style="style" :data-code-width="codeWidth" :data-widest-letter="widestLetter">
    <strong ref="measureElement" class="clause-code clause-code-measure" aria-hidden="true">WWWWWWWWWWWWWWWWWWWW</strong>
    <div v-for="clause in clauses" :key="clause.code" class="clause-row" data-testid="clause-row">
      <strong class="clause-code" data-testid="clause-code">{{ clause.code }}</strong>
      <span class="clause-title" data-testid="clause-title">{{ clause.title }}</span>
      <div v-if="sourceLabel || removable?.(clause.code)" class="clause-actions">
        <el-tag v-if="sourceLabel" size="small" effect="plain">{{ sourceLabel(clause.code) }}</el-tag>
        <el-button v-if="removable?.(clause.code)" text type="danger" @click="emit('remove', clause.code)">Remove</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.clause-list { position: relative; display: grid; gap: 8px; margin-bottom: 14px; min-width: 0; }
.clause-row { display: grid; grid-template-columns: var(--clause-code-width, 20em) minmax(0, 1fr) auto; column-gap: 12px; align-items: start; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; min-width: 0; }
.clause-code { font-size: 13px; font-weight: 500; text-align: left; overflow-wrap: anywhere; min-width: 0; }
.clause-code-measure { position: absolute; visibility: hidden; pointer-events: none; width: max-content; white-space: pre; overflow-wrap: normal; }
.clause-title { color: var(--text-secondary); font-size: 13px; text-align: left; overflow-wrap: anywhere; white-space: pre-wrap; min-width: 0; }
.clause-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
@media (max-width: 620px) { .clause-row { grid-template-columns: minmax(0, 1fr); row-gap: 6px; } }
</style>
