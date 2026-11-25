<script setup>
// 統計卡的迷你走勢線（2026-11-25）：資料來自 /api/dashboard 的 insights.trends，滑過看各月數字。
import { computed, ref } from 'vue'

const props = defineProps({
  values: { type: Array, default: () => [] },
  labels: { type: Array, default: () => [] },
  color: { type: String, default: '#AF2D41' },
  unit: { type: String, default: '' },
  name: { type: String, default: 'Trend' }
})
const W = 120, H = 28
const points = computed(() => {
  const list = props.values.map(Number)
  if (list.length < 2) return []
  const max = Math.max(...list), min = Math.min(...list), span = max - min || 1
  return list.map((v, i) => ({ x: 2 + i * (W - 4) / (list.length - 1), y: H - 3 - (v - min) / span * (H - 8), v, label: props.labels[i] }))
})
const active = ref(null)
const shown = computed(() => points.value[active.value ?? points.value.length - 1])
function onMove(event) {
  const box = event.currentTarget.getBoundingClientRect()
  active.value = Math.max(0, Math.min(points.value.length - 1, Math.round(((event.clientX - box.left) / box.width) * (points.value.length - 1))))
}
</script>

<template>
  <div v-if="points.length" class="spark" role="img" :aria-label="`${name}: ${points.map(p => p.v).join(', ')}`" @pointermove="onMove" @pointerleave="active = null">
    <svg class="spark-svg" :viewBox="`0 0 ${W} ${H}`" :width="W" :height="H">
      <path class="spark-line" :d="'M' + points.map(p => p.x + ' ' + p.y).join(' L')" fill="none" :stroke="color" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" pathLength="1" />
      <circle class="spark-dot" r="3" :cx="shown.x" :cy="shown.y" :fill="color" />
    </svg>
    <span class="spark-tip" :class="{ on: active != null }">{{ shown.label }} · {{ shown.v }}{{ unit }}</span>
  </div>
</template>
