<template>
  <div class="case-detail-panel" data-testid="case-detail-panel">
    <section class="block">
      <h3>案例标识</h3>
      <p class="mono case-id">{{ detail.case_id }}</p>
    </section>

    <section class="block">
      <h3>问题描述</h3>
      <p class="multiline">{{ detail.problem_description }}</p>
    </section>

    <section class="block">
      <h3>门店与品牌</h3>
      <dl class="kv">
        <div><dt>门店标识</dt><dd class="mono">{{ detail.store_profile.store_id }}</dd></div>
        <div><dt>门店名称</dt><dd>{{ detail.store_profile.store_name }}</dd></div>
        <div><dt>品牌标识</dt><dd class="mono">{{ detail.store_profile.brand_id }}</dd></div>
        <div><dt>品牌名称</dt><dd>{{ detail.store_profile.brand_name }}</dd></div>
        <div><dt>业态</dt><dd>{{ detail.store_profile.business_type }}</dd></div>
        <div><dt>门店规模</dt><dd>{{ detail.store_profile.store_scale }}</dd></div>
        <div><dt>加盟类型</dt><dd>{{ detail.store_profile.franchise_type }}</dd></div>
        <div><dt>城市</dt><dd>{{ detail.store_profile.city }}</dd></div>
        <div><dt>城市层级</dt><dd>{{ detail.store_profile.city_tier }}</dd></div>
      </dl>
    </section>

    <section class="block">
      <h3>分类与状态</h3>
      <dl class="kv">
        <div><dt>问题类型</dt><dd>{{ formatProblemType(detail.problem_type) }}</dd></div>
        <div><dt>状态</dt><dd>{{ formatStatus(detail.status) }}</dd></div>
        <div><dt>标签</dt><dd>{{ tagsLine }}</dd></div>
        <p v-if="!contractTags.length" class="hint">当前 OpenAPI 契约未包含标签字段；列表「标签」列待契约扩展后对齐。</p>
      </dl>
    </section>

    <section class="block">
      <h3>场景上下文</h3>
      <p class="multiline"><strong>场景</strong>：{{ detail.context.scene }}</p>
      <template v-if="contextExtras.length">
        <h4 class="sub">扩展字段</h4>
        <dl class="kv">
          <div v-for="row in contextExtras" :key="row.key">
            <dt>{{ row.key }}</dt>
            <dd class="multiline">{{ row.text }}</dd>
          </div>
        </dl>
      </template>
    </section>

    <section class="block">
      <h3>根因分析</h3>
      <p class="multiline">{{ detail.root_cause }}</p>
    </section>

    <section class="block">
      <h3>解决步骤</h3>
      <ol class="steps">
        <li v-for="step in sortedSteps" :key="step.order">
          <span class="step-order">{{ step.order }}.</span>
          <span class="multiline">{{ step.content }}</span>
        </li>
      </ol>
    </section>

    <section class="block">
      <h3>效果结果</h3>
      <dl class="kv">
        <div><dt>结果</dt><dd>{{ formatOutcome(detail.outcome.result) }}</dd></div>
        <div><dt>备注</dt><dd class="multiline">{{ detail.outcome.notes || '—' }}</dd></div>
      </dl>
    </section>

    <section class="block">
      <h3>时间</h3>
      <dl class="kv">
        <div><dt>创建时间</dt><dd>{{ detail.created_at }}</dd></div>
        <div><dt>更新时间</dt><dd>{{ detail.updated_at }}</dd></div>
      </dl>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CaseDetailResponse } from '@/api/cases'

const props = defineProps<{
  detail: CaseDetailResponse
}>()

type DetailWithTags = CaseDetailResponse & { tags?: string[] }

const contractTags = computed(() => {
  const t = (props.detail as DetailWithTags).tags
  return Array.isArray(t) ? t : []
})

const tagsLine = computed(() => (contractTags.value.length ? contractTags.value.join('、') : '—'))

const sortedSteps = computed(() =>
  [...props.detail.solution_steps].sort((a, b) => a.order - b.order)
)

const contextExtras = computed(() => {
  const ctx = props.detail.context as Record<string, unknown>
  const rows: { key: string; text: string }[] = []
  for (const [key, val] of Object.entries(ctx)) {
    if (key === 'scene') continue
    if (val === null || val === undefined) continue
    if (typeof val === 'string') rows.push({ key, text: val })
    else rows.push({ key, text: JSON.stringify(val) })
  }
  return rows
})

const problemLabels: Record<string, string> = {
  service: '服务',
  quality: '质量',
  operation: '运营',
  hygiene: '卫生',
  staffing: '人力',
  other: '其他',
}

const statusLabels: Record<string, string> = {
  draft: '草稿',
  active: '生效',
  archived: '归档',
}

const outcomeLabels: Record<string, string> = {
  improved: '改善',
  no_change: '无变化',
  unknown: '未知',
}

function formatProblemType(v: string): string {
  return problemLabels[v] ?? v
}

function formatStatus(v: string): string {
  return statusLabels[v] ?? v
}

function formatOutcome(v: string): string {
  return outcomeLabels[v] ?? v
}
</script>

<style scoped>
.case-detail-panel {
  max-width: 900px;
}

.block {
  margin-bottom: 24px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}

.block h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.sub {
  margin: 12px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.multiline {
  white-space: pre-wrap;
  word-break: break-word;
}

.kv {
  display: grid;
  gap: 8px 16px;
}

.kv > div {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 8px;
}

dt {
  color: #666;
  font-weight: 500;
}

dd {
  margin: 0;
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.case-id {
  font-size: 14px;
  word-break: break-all;
}

.steps {
  margin: 0;
  padding-left: 20px;
}

.step-order {
  font-weight: 600;
  margin-right: 6px;
}

.hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #888;
}
</style>
