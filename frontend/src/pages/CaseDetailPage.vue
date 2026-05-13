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

    <template v-else-if="detailPhase === 'success' && detail">
      <CaseDerivationStatusSection
        :phase="ancillaryPhase"
        :error-message="ancillaryError"
        :enrichment="enrichmentStatus"
        :vector="vectorStatus"
        :enrichment-retrying="enrichmentRetrying"
        :vector-retrying="vectorRetrying"
        data-testid="derivation-status"
        @reload="reloadAncillary"
        @retry-enrichment="onRetryEnrichment"
        @retry-vector="onRetryVector"
      />

      <CaseDetailPanel :detail="detail" />

      <p class="footer-actions">
        <router-link class="link" :to="{ name: 'case-edit', params: { id: caseId } }">编辑此案例</router-link>
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { createApiClient } from '@/api/client'
import { createCaseApiService } from '@/api/cases'
import {
  createEnrichmentApiService,
  type CaseEnrichmentStatusResponse,
} from '@/api/enrichment'
import {
  createVectorIndexingApiService,
  type VectorIndexStatusResponse,
} from '@/api/vectorIndexing'
import CaseDerivationStatusSection from '@/components/cases/CaseDerivationStatusSection.vue'
import CaseDetailPanel from '@/components/cases/CaseDetailPanel.vue'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import { isEnrichmentDetailOk } from '@/domain/caseDerivationStatus'
import { useCaseDetail } from '@/composables/useCases'

const route = useRoute()
const client = createApiClient()
const caseApi = createCaseApiService(client)
const enrichmentApi = createEnrichmentApiService(client)
const vectorApi = createVectorIndexingApiService(client)
const { detail, detailPhase, detailError, loadDetail, retryDetail } = useCaseDetail(caseApi)

const caseId = computed(() => String(route.params.id ?? ''))

const ancillaryPhase = ref<'idle' | 'loading' | 'success' | 'error'>('idle')
const ancillaryError = ref('')
const enrichmentStatus = ref<CaseEnrichmentStatusResponse | null>(null)
const vectorStatus = ref<VectorIndexStatusResponse | null>(null)
const enrichmentRetrying = ref(false)
const vectorRetrying = ref(false)

watch(
  caseId,
  (id) => {
    if (id) void loadDetail(id)
  },
  { immediate: true }
)

watch([caseId, detailPhase], ([id, phase]) => {
  ancillaryPhase.value = 'idle'
  enrichmentStatus.value = null
  vectorStatus.value = null
  ancillaryError.value = ''
  if (phase === 'success' && id) void loadAncillary(id)
})

async function loadAncillary(id: string): Promise<void> {
  ancillaryPhase.value = 'loading'
  ancillaryError.value = ''
  const [es, vs] = await Promise.all([
    enrichmentApi.getCaseEnrichmentStatus(id),
    vectorApi.getCaseVectorIndexStatus(id),
  ])
  const parts: string[] = []
  if (!es.ok) parts.push(`增强状态：${es.error.message}`)
  if (!vs.ok) parts.push(`向量状态：${vs.error.message}`)
  if (!es.ok || !vs.ok) {
    ancillaryPhase.value = 'error'
    ancillaryError.value = parts.join('；')
    return
  }
  enrichmentStatus.value = es.data
  vectorStatus.value = vs.data
  ancillaryPhase.value = 'success'
}

async function reloadAncillary(): Promise<void> {
  const id = caseId.value
  if (!id || detailPhase.value !== 'success') return
  await loadAncillary(id)
}

async function onRetryEnrichment(): Promise<void> {
  const id = caseId.value
  if (!id) return
  enrichmentRetrying.value = true
  const er = await enrichmentApi.createEnrichmentRun(id, {})
  enrichmentRetrying.value = false
  if (!er.ok) {
    ancillaryError.value = er.error.message
    ancillaryPhase.value = 'error'
    return
  }
  await loadAncillary(id)
}

async function onRetryVector(): Promise<void> {
  const id = caseId.value
  if (!id) return
  if (!isEnrichmentDetailOk(enrichmentStatus.value ?? { case_id: id, latest_run: null, current_result: null })) {
    return
  }
  vectorRetrying.value = true
  const latest = vectorStatus.value?.latest_job
  const st = latest?.status
  const res =
    latest?.job_id && (st === 'retryable' || st === 'failed')
      ? await vectorApi.retryVectorIndexJob(latest.job_id)
      : await vectorApi.refreshCaseVectorIndex(id, {
          force_rebuild: false,
          carry_retry_count: 0,
          requested_by: 'case-detail-retry',
        })
  vectorRetrying.value = false
  if (!res.ok) {
    ancillaryPhase.value = 'error'
    ancillaryError.value = res.error.message
    return
  }
  await loadAncillary(id)
}
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
