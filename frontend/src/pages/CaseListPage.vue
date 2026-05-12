<template>
  <div class="case-list-page">
    <h2>案例列表</h2>

    <CaseFilterBar v-model="filterModel" @submit="onSubmitFilters" />

    <LoadingState v-if="listPhase === 'loading'" message="正在加载案例列表…" />

    <ErrorNotice
      v-else-if="listPhase === 'error' && listError"
      :message="listError.message"
      :show-retry="true"
      @retry="retryInitial"
    />

    <template v-else-if="listPhase === 'empty'">
      <EmptyState title="暂无匹配案例" description="请调整筛选条件后重试，或创建新案例。" />
      <p v-if="lastPageMeta" class="page-meta-footer" data-testid="empty-page-meta">
        {{ emptyPageMetaLine }}
      </p>
    </template>

    <template v-else>
      <CaseTable
        :rows="displayRows"
        :has-next-page="hasNextPage"
        :is-loading-more="isLoadingMore"
        :load-more-error-message="loadMoreErrMsg"
        :last-page-meta="lastPageMeta"
        @load-more="loadMore"
        @retry-load-more="retryLoadMore"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@/api/client'
import { createCaseApiService, type CaseListItem } from '@/api/cases'
import CaseFilterBar from '@/components/cases/CaseFilterBar.vue'
import CaseTable from '@/components/cases/CaseTable.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import { useCaseList, type CaseListFilters } from '@/composables/useCases'

const client = createApiClient()
const caseApi = createCaseApiService(client)
const {
  items,
  listPhase,
  listError,
  lastPageMeta,
  hasNextPage,
  isLoadingMore,
  loadMoreError,
  loadInitial,
  loadMore,
  retryInitial,
  retryLoadMore,
} = useCaseList(caseApi)

const filterModel = ref<CaseListFilters>({})

type CaseListRow = CaseListItem & { tags?: string[] }

const tagTokens = computed(() => {
  const raw = filterModel.value.tags
  if (!raw?.trim()) return [] as string[]
  return raw
    .split(/[,，]/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
})

const displayRows = computed((): CaseListRow[] => {
  const rows = items.value as CaseListRow[]
  const tokens = tagTokens.value
  if (tokens.length === 0) return rows
  return rows.filter((row) => {
    const tags = row.tags
    if (tags?.length) {
      return tokens.every((t) => tags.some((x) => x.toLowerCase().includes(t)))
    }
    return tokens.every((t) => row.problem_description_preview.toLowerCase().includes(t))
  })
})

const emptyPageMetaLine = computed(() => {
  const m = lastPageMeta.value
  if (!m) return ''
  return `每页 ${m.limit} 条 · 排序：${m.sort} · 无下一页游标`
})

const loadMoreErrMsg = computed(() => loadMoreError.value?.message ?? '')

function onSubmitFilters(_f: CaseListFilters): void {
  void loadInitial(filterModel.value)
}

onMounted(() => {
  void loadInitial(filterModel.value)
})
</script>

<style scoped>
.case-list-page {
  padding: 20px;
}

.page-meta-footer {
  margin-top: 12px;
  font-size: 12px;
  color: #666;
  text-align: center;
}
</style>
