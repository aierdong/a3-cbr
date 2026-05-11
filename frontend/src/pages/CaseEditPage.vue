<template>
  <div class="case-edit-page">
    <h2>编辑案例</h2>
    <p>案例 ID: {{ caseId }}</p>
    <p>案例编辑页面（待实现）</p>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
const caseId = route.params.id
</script>

<style scoped>
.case-edit-page {
  padding: 20px;
}
</style>
