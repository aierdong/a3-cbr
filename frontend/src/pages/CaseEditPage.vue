<template>
  <Teleport to="body">
    <div
      v-if="blockingMessage"
      class="blocking-overlay"
      role="alertdialog"
      aria-live="polite"
      aria-busy="true"
      :aria-label="blockingMessage"
      data-testid="edit-blocking-overlay"
    >
      <div class="blocking-dialog">
        <p class="blocking-title">{{ blockingMessage }}</p>
        <p class="blocking-hint">请稍候，关闭或刷新页面可能中断操作。</p>
      </div>
    </div>
  </Teleport>

  <div class="case-edit-page">
    <h2>编辑案例</h2>

    <LoadingState v-if="detailPhase === 'loading'" message="正在加载案例…" />

    <ErrorNotice
      v-else-if="detailPhase === 'error' && detailError"
      :message="detailError.message"
      :show-retry="true"
      @retry="retryDetail"
    />

    <template v-else-if="detailPhase === 'success' && detail">
      <p v-if="pageError" class="page-error" role="alert">{{ pageError }}</p>

      <p v-if="enrichmentWarning" class="enrichment-warning" role="alert" data-testid="enrichment-warning">
        {{ enrichmentWarning }}
        <button
          type="button"
          class="btn-retry"
          :disabled="enrichmentRetrying"
          data-testid="enrichment-retry"
          @click="retryEnrichmentTrigger"
        >
          {{ enrichmentRetrying ? '重试中…' : '重试摘要与向量索引' }}
        </button>
      </p>

      <p v-if="vectorWarning" class="enrichment-warning" role="alert" data-testid="vector-warning">
        {{ vectorWarning }}
        <button
          type="button"
          class="btn-retry"
          :disabled="enrichmentRetrying"
          data-testid="vector-retry"
          @click="retryEnrichmentTrigger"
        >
          {{ enrichmentRetrying ? '重试中…' : '重试摘要与向量索引' }}
        </button>
      </p>

      <div v-if="successInfo" class="success-banner" data-testid="edit-success">
        已保存：案例标识 <span class="mono">{{ successInfo.case_id }}</span> · 状态
        {{ formatStatus(successInfo.status) }} · 更新时间 {{ successInfo.updated_at }}
      </div>

      <CaseForm
        mode="edit"
        :initial-detail="detail"
        :field-errors="fieldErrorMap"
        :submitting="submitting"
        @submit="onSubmit"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createApiClient } from '@/api/client'
import { createCaseApiService, type CaseDetailResponse, type UpdateCaseRequest } from '@/api/cases'
import { createEnrichmentApiService } from '@/api/enrichment'
import { createVectorIndexingApiService } from '@/api/vectorIndexing'
import { apiFieldErrorsToMap } from '@/api/errors'
import type { ApiError } from '@/api/errors'
import { runEnrichmentThenVectorRefresh } from '@/domain/submitWithSummaryPipeline'
import CaseForm from '@/components/cases/CaseForm.vue'
import type { CaseFormSubmitIntent } from '@/components/cases/CaseForm.vue'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import { useCaseDetail } from '@/composables/useCases'

const route = useRoute()
const router = useRouter()
const client = createApiClient()
const caseApi = createCaseApiService(client)
const enrichmentApi = createEnrichmentApiService(client)
const vectorApi = createVectorIndexingApiService(client)
const { detail, detailPhase, detailError, loadDetail, retryDetail } = useCaseDetail(caseApi)

const caseId = computed(() => String(route.params.id ?? ''))

watch(
  caseId,
  (id) => {
    if (id) void loadDetail(id)
  },
  { immediate: true }
)

const submitting = ref(false)
const fieldErrorMap = ref<Record<string, string>>({})
const pageError = ref('')
const successInfo = ref<{ case_id: string; status: string; updated_at: string } | null>(null)
const enrichmentWarning = ref('')
const vectorWarning = ref('')
const enrichmentRetrying = ref(false)
const blockingMessage = ref('')

const statusLabels: Record<string, string> = {
  draft: '草稿',
  active: '生效',
  archived: '归档',
}

function formatStatus(v: string): string {
  return statusLabels[v] ?? v
}

async function retryEnrichmentTrigger(): Promise<void> {
  const id = caseId.value
  if (!id) return
  enrichmentRetrying.value = true
  enrichmentWarning.value = ''
  vectorWarning.value = ''
  blockingMessage.value = '正在生成摘要，请稍候…'
  const pip = await runEnrichmentThenVectorRefresh({
    caseId: id,
    enrichmentApi,
    vectorApi,
    requestedBy: 'edit-page-retry',
    onBeforeVectorRefresh: () => {
      blockingMessage.value = '正在更新向量索引，请稍候…'
    },
  })
  enrichmentRetrying.value = false
  blockingMessage.value = ''
  if (!pip.ok) {
    if (pip.stage === 'enrichment') enrichmentWarning.value = pip.message
    else vectorWarning.value = pip.message
    await loadDetail(id)
    return
  }
  await loadDetail(id)
}

function setSubmitError(err: ApiError): void {
  fieldErrorMap.value = apiFieldErrorsToMap(err.fields)
  if (err.fields?.length) {
    pageError.value = '部分字段未通过校验，请修正后重试。'
  } else {
    pageError.value = err.message
  }
}

async function onSubmit(body: UpdateCaseRequest, meta: { intent: CaseFormSubmitIntent }): Promise<void> {
  const id = caseId.value
  if (!id) return
  pageError.value = ''
  fieldErrorMap.value = {}
  successInfo.value = null
  enrichmentWarning.value = ''
  vectorWarning.value = ''
  blockingMessage.value = '正在保存案例，请稍候…'
  submitting.value = true
  const res = await caseApi.update(id, body)
  blockingMessage.value = ''
  submitting.value = false
  if (!res.ok) {
    setSubmitError(res.error)
    return
  }
  const d: CaseDetailResponse = res.data
  successInfo.value = { case_id: d.case_id, status: d.status, updated_at: d.updated_at }
  if (meta.intent === 'submit-with-summary') {
    blockingMessage.value = '正在生成摘要，请稍候…'
    submitting.value = true
    const pip = await runEnrichmentThenVectorRefresh({
      caseId: id,
      enrichmentApi,
      vectorApi,
      onBeforeVectorRefresh: () => {
        blockingMessage.value = '正在更新向量索引，请稍候…'
      },
    })
    blockingMessage.value = ''
    submitting.value = false
    if (!pip.ok) {
      if (pip.stage === 'enrichment') enrichmentWarning.value = pip.message
      else vectorWarning.value = pip.message
      await loadDetail(id)
      return
    }
  }
  if (meta.intent === 'save-and-close' || meta.intent === 'submit-with-summary') {
    await router.push({ name: 'case-list' })
    return
  }
  await loadDetail(id)
}
</script>

<style scoped>
.case-edit-page {
  padding: 0;
}

.page-error {
  color: #c62828;
  margin-bottom: 12px;
}

.enrichment-warning {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #fff3e0;
  border: 1px solid #ffb74d;
  border-radius: 6px;
  color: #e65100;
  font-size: 14px;
}

.btn-retry {
  margin-left: 10px;
  padding: 4px 10px;
  border: 1px solid #e65100;
  border-radius: 4px;
  background: #fff;
  color: #e65100;
  cursor: pointer;
  font-size: 13px;
}

.btn-retry:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.success-banner {
  margin-bottom: 16px;
  padding: 12px 14px;
  background: #e8f5e9;
  border: 1px solid #a5d6a7;
  border-radius: 6px;
  font-size: 14px;
}

.mono {
  font-family: ui-monospace, monospace;
}

.blocking-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  padding: 16px;
}

.blocking-dialog {
  max-width: 420px;
  width: 100%;
  padding: 22px 24px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  text-align: center;
}

.blocking-title {
  margin: 0 0 10px;
  font-size: 16px;
  font-weight: 600;
  color: #1a1a1a;
}

.blocking-hint {
  margin: 0;
  font-size: 13px;
  color: #666;
  line-height: 1.5;
}
</style>
