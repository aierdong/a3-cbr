<template>
  <section class="derivation-block" data-testid="case-derivation-status">
    <h3>摘要与向量索引</h3>

    <p v-if="phase === 'loading'" class="hint">正在加载增强与向量状态…</p>

    <p v-else-if="phase === 'error'" class="derivation-error" role="alert">
      {{ errorMessage || '无法加载增强或向量状态' }}
      <button type="button" class="btn-retry" data-testid="derivation-reload" @click="$emit('reload')">重新加载</button>
    </p>

    <template v-else>
      <div class="row">
        <div class="label">增强</div>
        <div class="value">
          <span :class="enrichmentOk ? 'pill ok' : 'pill bad'">{{ enrichmentOk ? '已成功' : '未成功或无效' }}</span>
          <span class="sub">{{ enrichmentSummary }}</span>
          <button
            v-if="!enrichmentRetrying && !enrichmentOk"
            type="button"
            class="btn-inline"
            data-testid="retry-enrichment"
            @click="$emit('retry-enrichment')"
          >
            重试增强
          </button>
          <span v-if="enrichmentRetrying" class="busy">处理中…</span>
        </div>
      </div>
      <div class="row">
        <div class="label">向量化</div>
        <div class="value">
          <span :class="vectorOk ? 'pill ok' : 'pill bad'">{{ vectorOk ? '已成功' : '未成功或异常' }}</span>
          <span class="sub">{{ vectorSummary }}</span>
          <button
            v-if="!vectorRetrying && !vectorOk"
            type="button"
            class="btn-inline"
            data-testid="retry-vector"
            :disabled="!enrichmentOk"
            :title="!enrichmentOk ? '请先完成增强后再刷新向量索引' : ''"
            @click="$emit('retry-vector')"
          >
            {{ vectorRetryHint }}
          </button>
          <span v-if="vectorRetrying" class="busy">处理中…</span>
        </div>
      </div>
      <p v-if="!enrichmentOk" class="hint">向量化依赖成功增强；请先完成增强或重试增强。</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CaseEnrichmentStatusResponse } from '@/api/enrichment'
import type { VectorIndexStatusResponse } from '@/api/vectorIndexing'
import {
  formatEnrichmentSummary,
  formatVectorSummary,
  isEnrichmentDetailOk,
  isVectorDetailOk,
} from '@/domain/caseDerivationStatus'

const props = defineProps<{
  phase: 'idle' | 'loading' | 'success' | 'error'
  errorMessage?: string
  enrichment?: CaseEnrichmentStatusResponse | null
  vector?: VectorIndexStatusResponse | null
  enrichmentRetrying?: boolean
  vectorRetrying?: boolean
}>()

defineEmits<{
  reload: []
  'retry-enrichment': []
  'retry-vector': []
}>()

const enrichmentOk = computed(() => (props.enrichment ? isEnrichmentDetailOk(props.enrichment) : false))

const vectorOk = computed(() => (props.vector ? isVectorDetailOk(props.vector) : false))

const enrichmentSummary = computed(() =>
  props.enrichment ? formatEnrichmentSummary(props.enrichment) : ''
)

const vectorSummary = computed(() => (props.vector ? formatVectorSummary(props.vector) : ''))

const vectorRetryHint = computed(() => '重试/刷新向量索引')
</script>

<style scoped>
.derivation-block {
  margin-bottom: 24px;
  padding: 16px;
  background: #fafafa;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  max-width: 900px;
}

.derivation-block h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.row {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 8px 12px;
  margin-bottom: 10px;
  align-items: start;
}

.label {
  color: #666;
  font-weight: 500;
  font-size: 14px;
  padding-top: 2px;
}

.value {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.pill.ok {
  background: #e8f5e9;
  color: #2e7d32;
}

.pill.bad {
  background: #fff3e0;
  color: #e65100;
}

.sub {
  color: #555;
  flex: 1 1 160px;
}

.hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #777;
}

.busy {
  font-size: 13px;
  color: #666;
}

.derivation-error {
  margin: 0;
  color: #c62828;
  font-size: 14px;
}

.btn-inline,
.btn-retry {
  padding: 4px 10px;
  border: 1px solid #1976d2;
  border-radius: 4px;
  background: #fff;
  color: #1976d2;
  cursor: pointer;
  font-size: 13px;
}

.btn-inline:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
