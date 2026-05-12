<template>
  <article class="recommendation-card" :data-testid="`card-${item.rank}`">
    <header class="card-head">
      <h4 class="card-title">排序 #{{ item.rank }}</h4>
      <p class="sub">推荐项标识：{{ item.recommendation_item_id ?? '—（运行级占位）' }}</p>
      <p class="sub">案例标识：<span class="mono">{{ item.case_id }}</span></p>
    </header>

    <section class="section">
      <h5>案例引用</h5>
      <p><strong>标题预览：</strong>{{ item.case_reference.title_preview }}</p>
      <p><strong>描述预览：</strong>{{ item.case_reference.description_preview }}</p>
      <p v-if="item.case_reference.brand_summary"><strong>品牌摘要：</strong>{{ item.case_reference.brand_summary }}</p>
      <p v-if="item.case_reference.store_summary"><strong>门店摘要：</strong>{{ item.case_reference.store_summary }}</p>
      <p v-if="item.case_reference.filter_summary"><strong>过滤摘要：</strong>{{ item.case_reference.filter_summary }}</p>
      <p><strong>案例更新时间：</strong>{{ item.case_reference.case_updated_at }}</p>
    </section>

    <section class="section">
      <h5>核心步骤与效果</h5>
      <ul v-if="item.core_solution_steps?.length">
        <li v-for="(s, i) in item.core_solution_steps" :key="i">{{ s }}</li>
      </ul>
      <p v-else class="muted">无核心步骤</p>
      <p><strong>效果摘要：</strong>{{ item.outcome_summary ?? '—' }}</p>
      <p v-if="item.structured_suggestions_summary">
        <strong>结构化建议摘要：</strong>{{ item.structured_suggestions_summary }}
      </p>
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
      </ul>
      <p class="muted small">
        分值来源：<span class="mono">{{ item.score_breakdown.final_score_source }}</span>
      </p>
      <p v-if="item.score_breakdown.weights && Object.keys(item.score_breakdown.weights).length" class="muted small">
        权重明细：<span class="mono">{{ formatJson(item.score_breakdown.weights) }}</span>
      </p>

      <p><strong>解释状态：</strong>{{ item.explanation_status }} <span v-if="explanationHint" class="hint">— {{ explanationHint }}</span></p>
      <p v-if="runDegradedReason === 'explanation_fallback'" class="muted small">
        运行级降级：<span class="mono">explanation_fallback</span>（解释生成降级，展示可能为回退文案）
      </p>

      <p><strong>推荐理由：</strong>{{ item.recommendation_reason ?? '—' }}</p>
    </section>

    <section class="section">
      <h5>参考点 / 注意事项 / 来源</h5>
      <ul v-if="item.reference_points?.length">
        <li v-for="(p, i) in item.reference_points" :key="`rp-${i}`">{{ p }}</li>
      </ul>
      <p v-else class="muted">无可参考解决点</p>
      <ul v-if="item.cautions?.length">
        <li v-for="(c, i) in item.cautions" :key="`c-${i}`">{{ c }}</li>
      </ul>
      <p v-else class="muted">无注意事项</p>
      <ul v-if="item.source_references?.length">
        <li v-for="(s, i) in item.source_references" :key="`sr-${i}`">{{ s }}</li>
      </ul>
      <p v-else class="muted">无来源引用</p>
    </section>

    <section v-if="item.missing_fields.length" class="section warn" data-testid="card-missing">
      <h5>缺失字段提示</h5>
      <ul>
        <li v-for="f in item.missing_fields" :key="f" class="mono">{{ f }}</li>
      </ul>
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DegradedReason, ExplanationStatus, RecommendationItem } from '@/api/recommendations'

const props = defineProps<{
  item: RecommendationItem
  /** 运行级降级原因，用于与 `explanation_status` 组合提示 */
  runDegradedReason?: DegradedReason | null
}>()

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
</style>
