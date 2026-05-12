<template>
  <div class="case-create-page">
    <h2>创建案例</h2>

    <p v-if="pageError" class="page-error" role="alert">{{ pageError }}</p>

    <div v-if="successInfo" class="success-banner" data-testid="create-success">
      已保存：案例标识 <span class="mono">{{ successInfo.case_id }}</span> · 状态
      {{ formatStatus(successInfo.status) }} · 更新时间 {{ successInfo.updated_at }}
      <router-link class="detail-link" :to="{ name: 'case-detail', params: { id: successInfo.case_id } }">
        查看详情
      </router-link>
    </div>

    <CaseForm
      mode="create"
      :field-errors="fieldErrorMap"
      :submitting="submitting"
      @submit="onSubmit"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { createApiClient } from '@/api/client'
import { createCaseApiService, type CaseDetailResponse, type CreateCaseRequest, type UpdateCaseRequest } from '@/api/cases'
import { apiFieldErrorsToMap } from '@/api/errors'
import type { ApiError } from '@/api/errors'
import CaseForm from '@/components/cases/CaseForm.vue'

const client = createApiClient()
const caseApi = createCaseApiService(client)

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

async function onSubmit(payload: CreateCaseRequest | UpdateCaseRequest): Promise<void> {
  const body = payload as CreateCaseRequest
  pageError.value = ''
  fieldErrorMap.value = {}
  successInfo.value = null
  submitting.value = true
  const res = await caseApi.create(body)
  submitting.value = false
  if (!res.ok) {
    setSubmitError(res.error)
    return
  }
  const d: CaseDetailResponse = res.data
  successInfo.value = { case_id: d.case_id, status: d.status, updated_at: d.updated_at }
}
</script>

<style scoped>
.case-create-page {
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

.detail-link {
  margin-left: 12px;
}
</style>
