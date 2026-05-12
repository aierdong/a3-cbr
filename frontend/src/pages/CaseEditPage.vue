<template>
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
import { useRoute } from 'vue-router'
import { createApiClient } from '@/api/client'
import { createCaseApiService, type CaseDetailResponse, type UpdateCaseRequest } from '@/api/cases'
import { apiFieldErrorsToMap } from '@/api/errors'
import type { ApiError } from '@/api/errors'
import CaseForm from '@/components/cases/CaseForm.vue'
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

const submitting = ref(false)
const fieldErrorMap = ref<Record<string, string>>({})
const pageError = ref('')
const successInfo = ref<{ case_id: string; status: string; updated_at: string } | null>(null)

const statusLabels: Record<string, string> = {
  draft: '草稿',
  active: '生效',
  archived: '归档',
}

function formatStatus(v: string): string {
  return statusLabels[v] ?? v
}

function setSubmitError(err: ApiError): void {
  fieldErrorMap.value = apiFieldErrorsToMap(err.fields)
  if (err.fields?.length) {
    pageError.value = '部分字段未通过校验，请修正后重试。'
  } else {
    pageError.value = err.message
  }
}

async function onSubmit(body: UpdateCaseRequest): Promise<void> {
  const id = caseId.value
  if (!id) return
  pageError.value = ''
  fieldErrorMap.value = {}
  successInfo.value = null
  submitting.value = true
  const res = await caseApi.update(id, body)
  submitting.value = false
  if (!res.ok) {
    setSubmitError(res.error)
    return
  }
  const d: CaseDetailResponse = res.data
  successInfo.value = { case_id: d.case_id, status: d.status, updated_at: d.updated_at }
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
</style>
