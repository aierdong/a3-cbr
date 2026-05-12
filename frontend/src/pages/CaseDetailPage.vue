<template>
  <div class="case-detail-page">
    <h2>案例详情</h2>

    <LoadingState v-if="detailPhase === 'loading'" message="正在加载案例详情…" />

    <ErrorNotice
      v-else-if="detailPhase === 'error' && detailError"
      :message="detailError.message"
      :show-retry="true"
      @retry="retryDetail"
    />

    <CaseDetailPanel v-else-if="detailPhase === 'success' && detail" :detail="detail" />

    <p v-if="detailPhase === 'success' && detail" class="footer-actions">
      <router-link class="link" :to="{ name: 'case-edit', params: { id: caseId } }">编辑此案例</router-link>
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { createApiClient } from '@/api/client'
import { createCaseApiService } from '@/api/cases'
import CaseDetailPanel from '@/components/cases/CaseDetailPanel.vue'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import { useCaseDetail } from '@/composables/useCases'

const route = useRoute()
const client = createApiClient()
const caseApi = createCaseApiService(client)
const { detail, detailPhase, detailError, loadDetail, retryDetail } = useCaseDetail(caseApi)

const caseId = computed(() => String(route.params.id ?? ''))

watch(
  caseId,
  (id) => {
    if (id) void loadDetail(id)
  },
  { immediate: true }
)
</script>

<style scoped>
.case-detail-page {
  padding: 0;
}

.footer-actions {
  margin-top: 16px;
}

.link {
  color: #1976d2;
}
</style>
