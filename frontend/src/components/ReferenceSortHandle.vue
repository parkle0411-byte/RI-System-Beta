<script setup>
defineProps({ disabled: Boolean, label: String })
const emit = defineEmits(['start', 'end', 'move'])
function start(event) {
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', 'reference-row')
  emit('start', event)
}
</script>

<template>
  <button type="button" class="sort-handle" :disabled="disabled" :draggable="!disabled"
    :aria-label="`Reorder ${label}`" title="Drag to reorder. Use Up or Down arrow keys to move."
    @dragstart.stop="start" @dragend="emit('end')"
    @keydown.up.prevent="emit('move', -1)" @keydown.down.prevent="emit('move', 1)">
    <svg width="16" height="20" viewBox="0 0 16 20" aria-hidden="true" fill="currentColor">
      <circle v-for="n in 6" :key="n" :cx="n % 2 ? 5 : 11" :cy="4 + Math.floor((n - 1) / 2) * 6" r="1.5" />
    </svg>
  </button>
</template>

<style scoped>
.sort-handle { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 36px; border: 1px solid transparent; border-radius: 5px; background: transparent; color: #606775; cursor: grab; }
.sort-handle:hover, .sort-handle:focus-visible { background: #edf4ff; border-color: #409eff; outline: none; }
.sort-handle:active { cursor: grabbing; }
.sort-handle:disabled { opacity: .4; cursor: default; }
</style>
