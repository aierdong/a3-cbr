<template>
  <div class="case-detail-page">
    <h2>案例详情</h2>
    <p>案例 ID: {{ caseId }}</p>
    <p>案例详情页面（待实现）</p>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
const caseId = route.params.id
</script>

<style scoped>
.case-detail-page {
  padding: 20px;
}
</style>
