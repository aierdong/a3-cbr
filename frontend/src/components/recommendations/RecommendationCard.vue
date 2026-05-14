<template>
  <article class="recommendation-card" :data-testid="`card-${item.rank}`">
    <header class="card-head">
      <h4 class="card-title">排序 #{{ item.rank }}</h4>
      <p class="sub">推荐项标识：<span class="mono">{{ item.recommendation_item_id }}</span></p>
      <p class="sub">案例标识：<span class="mono">{{ item.case_id }}</span></p>
    </header>

    <section class="section">
      <h5>案例引用</h5>
      <p><strong>描述摘要：</strong>{{ caseDescriptionLine(item) }}</p>
      <p v-if="item.case_reference.brand_summary"><strong>品牌摘要：</strong>{{ item.case_reference.brand_summary }}</p>
      <p v-if="item.case_reference.store_summary"><strong>门店摘要：</strong>{{ item.case_reference.store_summary }}</p>
      <p v-if="item.case_reference.filter_summary"><strong>过滤摘要：</strong>{{ item.case_reference.filter_summary }}</p>
      <p><strong>案例更新时间：</strong>{{ caseUpdatedAtLine(item) }}</p>
    </section>

    <section class="section">
      <h5>核心步骤与效果</h5>
      <p class="cautions-block"><strong>推荐理由：</strong></p>
      <p>{{ item.recommendation_reason ?? '—' }}</p>
      <p class="cautions-block"><strong>解决步骤：</strong></p>
      <ol v-if="coreSolutionStepsLine(item).length" class="solution">
        <li v-for="(step, idx) in coreSolutionStepsLine(item)" :key="idx" class="steps-text">
          {{ step.trim() }}
        </li>
      </ol>
      <p v-else class="muted">无核心步骤</p>
      <p class="top-space cautions-block"><strong>效果摘要：</strong></p>
      <p>{{ item.outcome_summary ?? '—' }}</p>
      <div v-if="item.cautions?.length" class="cautions-block">
        <p><strong>注意事项：</strong></p>
        <ul class="bullet-list">
          <li v-for="(c, i) in item.cautions" :key="`caution-${i}`">{{ c }}</li>
        </ul>
      </div>
    </section>

    <section class="section">
      <h5>分值与解释</h5>
      <ul class="scores" data-testid="card-scores">
        <li><strong>向量相似度：</strong>{{ formatScore(item.vector_similarity_score) }}</li>
        <li>
          <strong>语义相似度：</strong>
          <span v-if="item.semantic_similarity_score != null">{{ formatScore(item.semantic_similarity_score) }}</span>
          <span v-else class="degraded-inline" data-testid="semantic-null">不可用（服务端降级或未返回）</span>
        </li>
        <li>
          <strong>结构化相似度：</strong>
          <span v-if="item.structured_similarity_score != null">{{ formatScore(item.structured_similarity_score) }}</span>
          <span v-else class="degraded-inline" data-testid="structured-null">不可用（服务端降级或未返回）</span>
        </li>
        <li><strong>业务参数分：</strong>{{ item.business_score != null ? formatScore(item.business_score) : '—' }}</li>
        <li><strong>最终聚合分：</strong>{{ formatScore(item.final_score) }}</li>
        <li><strong>分值来源：</strong><span class="mono">{{ item.score_metadata.final_score_source }}</span></li>
        <li v-if="effectiveWeightsLine(item)">
          <strong>有效权重：</strong>
          <span class="mono">{{ formatJson(effectiveWeightsLine(item)!) }}</span></li>
        <li><strong>解释状态：</strong>{{ item.explanation_status }} <span v-if="explanationHint" class="hint">— {{ explanationHint }}</span></li>
        <li v-if="runDegradedReason === 'explanation_fallback'">
          <strong>运行级降级：</strong>
          <span class="mono">explanation_fallback</span>
          <span class="hint">（解释生成降级，展示可能为回退文案）</span>
        </li>
      </ul>

    </section>

    <section v-if="item.missing_fields.length" class="section warn" data-testid="card-missing">
      <h5>缺失字段提示</h5>
      <ul>
        <li v-for="f in item.missing_fields" :key="f" class="mono">{{ f }}</li>
      </ul>
    </section>

    <section v-if="item.recommendation_item_id && recommendationRunId && feedbackApi" class="section">
      <FeedbackControls
        :feedback-api="feedbackApi"
        :recommendation-run-id="recommendationRunId"
        :recommendation-item-id="item.recommendation_item_id"
      />
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FeedbackApiService } from '@/api/feedback'
import type { ExplanationStatus, RecommendationItem } from '@/api/recommendations'
import FeedbackControls from '@/components/recommendations/FeedbackControls.vue'

const props = defineProps<{
  item: RecommendationItem
  /** 运行级降级原因（与响应 `degraded_reason` 字符串一致） */
  runDegradedReason?: string | null
  /** 与列表页传入一致，用于推荐项级反馈 */
  recommendationRunId?: string
  feedbackApi?: FeedbackApiService
}>()

function caseRefRecord(item: RecommendationItem): Record<string, unknown> {
  return item.case_reference as unknown as Record<string, unknown>
}

function caseEnrichmentBlock(item: RecommendationItem): Record<string, unknown> | null {
  const r = caseRefRecord(item)
  const cer = r.case_enrichment_results
  if (cer && typeof cer === 'object' && !Array.isArray(cer)) {
    return cer as Record<string, unknown>
  }
  return null
}

function caseDescriptionLine(item: RecommendationItem): string {
  const r = caseRefRecord(item)
  const dp = r.description_preview
  if (typeof dp === 'string' && dp.trim()) return dp
  const en = caseEnrichmentBlock(item)
  const ps = en?.problem_summary
  if (typeof ps === 'string' && ps.trim()) return ps
  return '（暂无摘要预览，仅返回案例标识）'
}

function coreSolutionStepsLine(item: RecommendationItem): string[] {
  const s = item.core_solution_steps
  if (typeof s === 'string' && s.trim()) {
    return s.split('；').filter(t => t.trim())
  }
  const en = caseEnrichmentBlock(item)
  const ss = en?.solution_summary
  if (typeof ss === 'string' && ss.trim()) {
    return ss.split('；').filter(t => t.trim())
  }
  return []
}

function caseUpdatedAtLine(item: RecommendationItem): string {
  const r = caseRefRecord(item)
  const u = r.case_updated_at
  if (typeof u === 'string' && u.trim()) {
    // Example input: "2026-05-14T07:42:02.467614+00:00"
    // Desired output: "2026-05-14 07:42:02"
    const match = u.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/)
    if (match) {
      return `${match[1]} ${match[2]}`
    }
    return u
  }
  return '—'
}

function effectiveWeightsLine(item: RecommendationItem): Record<string, number> | null {
  const w = item.score_metadata.effective_weights
  return w && Object.keys(w).length > 0 ? w : null
}

function formatScore(n: number): string {
  return Number.isFinite(n) ? n.toFixed(4) : String(n)
}

function formatJson(v: object): string {
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

const explanationHints: Partial<Record<ExplanationStatus, string>> = {
  generated: '解释已生成',
  fallback: '解释降级为回退文案',
  unavailable: '解释不可用',
}

const explanationHint = computed(() => explanationHints[props.item.explanation_status] ?? '')
</script>

<style scoped>
.recommendation-card {
  margin-bottom: 1rem;
  padding: 1rem;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}

.card-head {
  margin-bottom: 10px;
}

.card-title {
  font-size: 15px;
  margin: 0 0 6px;
}

.sub {
  margin: 2px 0;
  font-size: 12px;
  color: #555;
}

.section {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
}

.section.warn {
  border-color: #ffe0b2;
  background: #fff8e1;
  padding: 10px;
  border-radius: 4px;
}

.section h5 {
  font-size: 13px;
  margin: 0 0 6px;
  color: #333;
}

.scores {
  margin: 0;
  padding-left: 18px;
}

.muted {
  color: #777;
}

.small {
  font-size: 12px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.degraded-inline {
  color: #b26a00;
}

.hint {
  color: #555;
  font-size: 12px;
}

.steps-text {
  margin: 0;
  white-space: pre-wrap;
}

.subheading {
  margin: 10px 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: #444;
}

.cautions-block {
  margin-top: 8px;
}

.bullet-list {
  margin: 0;
  padding-left: 18px;
}

.solution {
  margin-left: 14px;
}

h5 {
  background-color: rgba(135, 206, 235, 0.5);
  min-height: 18px;
}
</style>
