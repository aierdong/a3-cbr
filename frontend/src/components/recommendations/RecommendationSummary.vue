<template>
  <section class="recommendation-summary" aria-label="推荐运行摘要">
    <h3 class="summary-title">推荐运行摘要</h3>
    <dl class="summary-grid">
      <dt>推荐运行标识</dt>
      <dd data-testid="sum-run-id">{{ response.recommendation_run_id }}</dd>

      <dt>契约版本</dt>
      <dd>{{ response.contract_version }}</dd>

      <dt>检索状态</dt>
      <dd data-testid="sum-status">
        <span class="status-pill">{{ response.status }}</span>
        <span v-if="statusHint" class="hint"> — {{ statusHint }}</span>
      </dd>

      <dt v-if="response.message">状态说明</dt>
      <dd v-if="response.message">{{ response.message }}</dd>

      <dt v-if="response.error_code">错误码</dt>
      <dd v-if="response.error_code">{{ response.error_code }}</dd>

      <dt v-if="response.degraded_reason">降级原因</dt>
      <dd v-if="response.degraded_reason" data-testid="sum-degraded">
        <span class="mono">{{ response.degraded_reason }}</span>
        <span v-if="degradedHint"> — {{ degradedHint }}</span>
      </dd>

      <dt>查询哈希</dt>
      <dd class="mono">{{ response.query_metadata.query_hash }}</dd>

      <dt>请求 Top-K</dt>
      <dd data-testid="sum-req-k">{{ response.query_metadata.requested_top_k }}</dd>

      <dt>向量候选数</dt>
      <dd data-testid="sum-candidates">{{ response.query_metadata.vector_candidate_count }}</dd>

      <dt>返回条数</dt>
      <dd data-testid="sum-returned">{{ response.query_metadata.returned_count }}</dd>

      <dt>延迟（ms）</dt>
      <dd>{{ response.query_metadata.latency_ms }}</dd>
    </dl>

    <div class="block">
      <h4>分值权重（服务端返回）</h4>
      <pre class="json-block" data-testid="sum-score-weights">{{ formatJson(response.score_weights) }}</pre>
    </div>

    <div class="block">
      <h4>实际应用的过滤条件</h4>
      <pre class="json-block" data-testid="sum-applied-filters">{{ formatJson(response.applied_filters) }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DegradedReason, RecommendationResponse, RecommendationStatus } from '@/api/recommendations'

const props = defineProps<{
  response: RecommendationResponse
}>()

function formatJson(v: object): string {
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

const degradedHints: Record<DegradedReason, string> = {
  query_summarization_failed: '查询理解服务降级，推荐结果可能不够精确',
  vector_search_failed: '向量搜索服务降级，推荐结果可能不够精确',
  no_candidates: '未找到匹配的候选案例',
  reranker_failed: '推荐排序服务降级，结果按向量相似度排序',
  aggregation_failed: '分值聚合服务降级，结果按向量相似度排序',
  reranker_and_aggregation_failed: '推荐排序和分值聚合服务降级，结果按向量相似度排序',
  explanation_fallback: '推荐解释生成降级，使用默认解释文案',
  partial_candidate_data: '部分案例数据不完整',
}

const statusHints: Partial<Record<RecommendationStatus, string>> = {
  succeeded: '检索成功',
  empty: '无可用推荐项',
  degraded: '检索成功但存在降级路径',
  failed: '检索失败',
}

const degradedHint = computed(() => {
  const r = props.response.degraded_reason
  return r ? degradedHints[r] ?? '' : ''
})

const statusHint = computed(() => statusHints[props.response.status] ?? '')
</script>

<style scoped>
.recommendation-summary {
  margin-bottom: 1.25rem;
  padding: 1rem;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}

.summary-title {
  font-size: 16px;
  margin-bottom: 12px;
}

.summary-grid {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 8px 12px;
  align-items: start;
}

dt {
  color: #666;
  font-size: 12px;
}

dd {
  margin: 0;
  font-size: 14px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  word-break: break-all;
}

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  background: #e3f2fd;
  color: #0d47a1;
  font-size: 12px;
}

.hint {
  color: #555;
  font-size: 13px;
}

.block {
  margin-top: 14px;
}

.block h4 {
  font-size: 13px;
  margin-bottom: 6px;
  color: #444;
}

.json-block {
  margin: 0;
  padding: 10px;
  background: #fafafa;
  border: 1px solid #eee;
  border-radius: 4px;
  max-height: 220px;
  overflow: auto;
  font-size: 12px;
}
</style>
