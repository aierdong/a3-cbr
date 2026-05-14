<template>
  <div class="case-list-page">
    <header class="page-header">
      <h2>案例列表</h2>
      <router-link
        :to="{ name: 'case-create' }"
        class="btn-create"
        data-testid="case-create-nav"
      >
        创建案例
      </router-link>
    </header>

    <CaseFilterBar v-model="filterModel" @submit="onSubmitFilters" />

    <LoadingState v-if="listPhase === 'loading'" message="正在加载案例列表…" />

    <ErrorNotice
      v-else-if="listPhase === 'error' && listError"
      :message="listError.message"
      :show-retry="true"
      @retry="retryInitial"
    />

    <template v-else-if="listPhase === 'empty'">
      <EmptyState :title="emptyStateTitle" :description="emptyStateDescription">
        <template #action>
          <router-link
            :to="{ name: 'case-create' }"
            class="btn-create-inline"
            data-testid="case-create-empty-cta"
          >
            创建案例
          </router-link>
        </template>
      </EmptyState>
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
import { createCaseApiService } from '@/api/cases'
import CaseFilterBar from '@/components/cases/CaseFilterBar.vue'
import CaseTable from '@/components/cases/CaseTable.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import { useCaseList, type CaseListFilters } from '@/composables/useCases'
import { listItemProblemPreview, type CaseListRowApi } from '@/domain/caseListDisplay'

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
  currentFilters,
  loadInitial,
  loadMore,
  retryInitial,
  retryLoadMore,
} = useCaseList(caseApi)

const filterModel = ref<CaseListFilters>({})

const hasActiveListFilters = computed(() => {
  const f = currentFilters.value
  return Boolean(
    f.brand_id?.trim() ||
      f.store_id?.trim() ||
      f.problem_type ||
      f.status ||
      f.tags?.trim() ||
      f.created_from?.trim() ||
      f.created_to?.trim() ||
      f.include_archived === true
  )
})

const emptyStateTitle = computed(() =>
  hasActiveListFilters.value ? '暂无匹配案例' : '暂无案例'
)

const emptyStateDescription = computed(() =>
  hasActiveListFilters.value
    ? '请调整筛选条件后重试，或创建新案例。'
    : '当前尚无任何案例数据，可点击右上方按钮创建第一条案例。'
)

type CaseListRow = CaseListRowApi & { tags?: string[] }

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
    return tokens.every((t) =>
      listItemProblemPreview(row).toLowerCase().includes(t),
    )
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

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.btn-create {
  flex-shrink: 0;
  display: inline-block;
  padding: 8px 16px;
  border-radius: 4px;
  background: #1976d2;
  color: #fff;
  text-decoration: none;
  font-size: 14px;
  border: 1px solid #1976d2;
}

.btn-create:hover {
  background: #1565c0;
  border-color: #1565c0;
}

.btn-create-inline {
  display: inline-block;
  margin-top: 1rem;
  padding: 8px 16px;
  border-radius: 4px;
  background: #1976d2;
  color: #fff;
  text-decoration: none;
  font-size: 14px;
  border: 1px solid #1976d2;
}

.btn-create-inline:hover {
  background: #1565c0;
  border-color: #1565c0;
}

.page-meta-footer {
  margin-top: 12px;
  font-size: 12px;
  color: #666;
  text-align: center;
}
</style>
