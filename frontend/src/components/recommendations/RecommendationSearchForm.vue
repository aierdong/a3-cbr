<template>
  <section class="recommendation-search-form" aria-label="相似案例检索条件">
    <form @submit.prevent="onSubmit">
      <div class="filter-grid">
        <label class="field wide">
          <span class="label">当前问题描述 <span class="req">*</span></span>
          <textarea
            v-model.trim="localDraft.query_text"
            rows="4"
            required
            maxlength="8000"
            placeholder="描述当前问题，用于相似案例检索"
            autocomplete="off"
          />
          <p v-if="fieldErrors.query_text" class="field-error" data-testid="err-query_text">
            {{ fieldErrors.query_text }}
          </p>
        </label>

        <label class="field">
          <span class="label">Top-K</span>
          <input
            v-model.number="localDraft.top_k"
            type="number"
            min="1"
            max="100"
            step="1"
            data-testid="input-top_k"
          />
          <p v-if="fieldErrors.top_k" class="field-error">{{ fieldErrors.top_k }}</p>
        </label>

        <label class="field">
          <span class="label">品牌 ID</span>
          <input v-model.trim="localDraft.brand_id" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">门店 ID</span>
          <input v-model.trim="localDraft.store_id" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">问题类型</span>
          <select v-model="localDraft.problem_type">
            <option value="">不限</option>
            <option v-for="opt in CASE_PROBLEM_TYPE_OPTIONS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </label>
        <label class="field">
          <span class="label">案例状态</span>
          <select v-model="localDraft.case_status">
            <option value="">不限</option>
            <option value="draft">草稿</option>
            <option value="active">生效</option>
            <option value="archived">归档</option>
          </select>
        </label>
        <label class="field wide">
          <span class="label">标签（逗号分隔）</span>
          <input v-model.trim="localDraft.tags" type="text" autocomplete="off" placeholder="例如：客诉, 卫生" />
        </label>
        <label class="field">
          <span class="label">业态</span>
          <input v-model.trim="localDraft.business_type" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">门店规模</span>
          <input v-model.trim="localDraft.store_scale" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">加盟类型</span>
          <input v-model.trim="localDraft.franchise_type" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">城市</span>
          <input v-model.trim="localDraft.city" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">城市层级</span>
          <input v-model.trim="localDraft.city_tier" type="text" autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">创建时间起</span>
          <input v-model="localDraft.created_at_from_local" type="datetime-local" />
        </label>
        <label class="field">
          <span class="label">创建时间止</span>
          <input v-model="localDraft.created_at_to_local" type="datetime-local" />
        </label>
      </div>

      <div class="actions">
        <button type="submit" class="btn primary" data-testid="search-submit" :disabled="submitting">
          {{ submitting ? '检索中…' : '检索相似案例' }}
        </button>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { RecommendationSearchDraft } from '@/composables/useRecommendations'
import { defaultRecommendationSearchDraft } from '@/composables/useRecommendations'
import { CASE_PROBLEM_TYPE_OPTIONS } from '@/domain/caseProblemType'

const props = defineProps<{
  modelValue: RecommendationSearchDraft
  fieldErrors: Record<string, string>
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: RecommendationSearchDraft]
  submit: []
}>()

const localDraft = reactive<RecommendationSearchDraft>({
  ...defaultRecommendationSearchDraft(),
  ...props.modelValue,
})

watch(
  () => props.modelValue,
  (v) => {
    Object.assign(localDraft, defaultRecommendationSearchDraft(), v)
  },
  { deep: true }
)

function onSubmit(): void {
  emit('update:modelValue', { ...localDraft })
  emit('submit')
}
</script>

<style scoped>
.recommendation-search-form {
  margin-bottom: 1.25rem;
  padding: 1rem;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem 1rem;
  align-items: start;
}

.field.wide {
  grid-column: 1 / -1;
}

.label {
  display: block;
  font-size: 12px;
  color: #555;
  margin-bottom: 4px;
}

.req {
  color: #c62828;
}

.field textarea,
.field input[type='text'],
.field input[type='number'],
.field input[type='datetime-local'],
.field select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-sizing: border-box;
}

.field-error {
  margin-top: 4px;
  font-size: 12px;
  color: #c62828;
}

.actions {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
}

.btn {
  padding: 6px 14px;
  border-radius: 4px;
  border: 1px solid #ccc;
  background: #fafafa;
}

.btn.primary {
  background: #1976d2;
  color: #fff;
  border-color: #1976d2;
}

.btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
</style>
