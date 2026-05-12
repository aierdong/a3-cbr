<template>
  <div class="recommendation-page">
    <h2>相似案例检索</h2>

    <RecommendationSearchForm
      v-model="draft"
      :field-errors="fieldErrors"
      :submitting="submitting"
      @submit="onSubmitSearch"
    />

    <LoadingState v-if="submitting" message="正在检索相似案例…" />

    <ErrorNotice
      v-else-if="pageError && !lastResult"
      :message="pageError.message"
      :show-retry="pageError.kind === 'dependency_unavailable' || pageError.kind === 'system' || pageError.kind === 'network'"
      @retry="onSubmitSearch"
    />

    <div v-else-if="pageError && lastResult" class="inline-error">
      <ErrorNotice
        :message="pageError.message"
        :show-retry="pageError.kind === 'dependency_unavailable' || pageError.kind === 'system' || pageError.kind === 'network'"
        @retry="onSubmitSearch"
      />
    </div>

    <template v-if="lastResult && !submitting">
      <RecommendationSummary :response="lastResult" />

      <EmptyState
        v-if="lastResult.items.length === 0"
        title="暂无推荐项"
        :description="emptyDescription"
      />

      <div v-else class="cards">
        <RecommendationCard
          v-for="it in lastResult.items"
          :key="itemKey(it)"
          :item="it"
          :run-degraded-reason="lastResult.degraded_reason"
        />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { createApiClient } from '@/api/client'
import { createRecommendationApiService, type RecommendationItem } from '@/api/recommendations'
import RecommendationCard from '@/components/recommendations/RecommendationCard.vue'
import RecommendationSearchForm from '@/components/recommendations/RecommendationSearchForm.vue'
import RecommendationSummary from '@/components/recommendations/RecommendationSummary.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import { useRecommendations } from '@/composables/useRecommendations'

const client = createApiClient()
const recommendationApi = createRecommendationApiService(client)
const { draft, lastResult, submitting, pageError, fieldErrors, search } = useRecommendations(recommendationApi)

const emptyDescription = computed(() => {
  const r = lastResult.value
  if (!r) return ''
  if (r.status === 'empty') return '后端返回空结果；可调整问题描述或过滤条件后重试。'
  if (r.degraded_reason === 'no_candidates') return '候选不足或未找到匹配案例。'
  return '当前无返回条目；请查看上方运行摘要中的状态与降级说明。'
})

function itemKey(it: RecommendationItem): string {
  return it.recommendation_item_id ?? `${it.case_id}-${it.rank}`
}

async function onSubmitSearch(): Promise<void> {
  await search()
}
</script>

<style scoped>
.recommendation-page {
  padding: 20px;
}

.cards {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.inline-error {
  margin: 8px 0 12px;
}
</style>
