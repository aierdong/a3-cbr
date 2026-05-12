<template>
  <section
    class="feedback-controls"
    :aria-label="sectionLabel"
    :data-testid="dataTestId"
  >
    <h5 class="fb-title">{{ title }}</h5>

    <div class="fb-row" role="radiogroup" :aria-label="title + '有用性'">
      <label v-for="opt in usefulnessOptions" :key="opt.value" class="fb-radio">
        <input
          v-model="usefulness"
          type="radio"
          :name="radioName"
          :value="opt.value"
          :disabled="submitting"
        />
        {{ opt.label }}
      </label>
    </div>

    <div class="fb-field">
      <label :for="commentFieldId">备注（可选）</label>
      <textarea
        :id="commentFieldId"
        v-model="commentDraft"
        class="fb-textarea"
        rows="3"
        maxlength="2000"
        :disabled="submitting"
        placeholder="最多 2000 字"
      />
      <p v-if="controlError?.fieldMessages.comment" class="fb-field-err" role="alert">
        {{ controlError.fieldMessages.comment }}
      </p>
    </div>

    <div class="fb-actions">
      <button
        type="button"
        class="fb-submit"
        data-testid="feedback-submit"
        :disabled="submitting"
        @click="onSubmit"
      >
        {{ submitting ? '提交中…' : '提交反馈' }}
      </button>
    </div>

    <p v-if="successInfo" class="fb-success" data-testid="feedback-success">
      已保存 · 目标范围 {{ targetScopeLabel(successInfo.target_scope) }} · 更新时间
      {{ formatSavedAt(successInfo.updated_at) }}
    </p>

    <ErrorNotice
      v-if="controlError"
      class="fb-error"
      data-testid="feedback-error"
      :message="controlError.message"
      :show-retry="controlError.showRetry"
      @retry="onSubmit"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  FeedbackApiService,
  FeedbackControlErrorState,
  FeedbackResponse,
  TargetScope,
  Usefulness,
} from '@/api/feedback'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import { useFeedbackSubmit } from '@/composables/useFeedback'

const props = defineProps<{
  feedbackApi: FeedbackApiService
  recommendationRunId: string
  /** 非空时为推荐项级反馈；省略或 null 为运行级 */
  recommendationItemId?: string | null
}>()

const usefulness = ref<Usefulness>('unknown')
const commentDraft = ref('')
const submitting = ref(false)
const successInfo = ref<FeedbackResponse | null>(null)
const controlError = ref<FeedbackControlErrorState | null>(null)

const { submit } = useFeedbackSubmit(props.feedbackApi)

const isItemScope = computed(() => {
  const id = props.recommendationItemId
  return id != null && String(id).trim() !== ''
})

const radioName = computed(
  () => `fb-usefulness-${props.recommendationRunId}-${isItemScope.value ? props.recommendationItemId : 'run'}`
)

const commentFieldId = computed(() => `${radioName.value}-comment`)

const dataTestId = computed(() =>
  isItemScope.value ? `feedback-item-${props.recommendationItemId}` : 'feedback-run'
)

const title = computed(() => (isItemScope.value ? '本条推荐反馈' : '本次推荐反馈'))

const sectionLabel = computed(() => title.value)

const usefulnessOptions: { value: Usefulness; label: string }[] = [
  { value: 'useful', label: '有用' },
  { value: 'not_useful', label: '无用' },
  { value: 'unknown', label: '不确定' },
]

watch(
  () => [props.recommendationRunId, props.recommendationItemId] as const,
  () => {
    successInfo.value = null
    controlError.value = null
    usefulness.value = 'unknown'
    commentDraft.value = ''
  }
)

function targetScopeLabel(scope: TargetScope): string {
  return scope === 'item' ? '推荐项' : '推荐运行'
}

function formatSavedAt(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

async function onSubmit(): Promise<void> {
  controlError.value = null
  submitting.value = true
  try {
    const trimmed = commentDraft.value.trim()
    const itemId = isItemScope.value ? props.recommendationItemId!.trim() : null
    const result = await submit({
      recommendation_run_id: props.recommendationRunId,
      recommendation_item_id: itemId,
      usefulness: usefulness.value,
      comment: trimmed.length ? trimmed : null,
    })
    if (!result.ok) {
      controlError.value = result.control
      return
    }
    successInfo.value = result.data
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.feedback-controls {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  background: #fafafa;
}

.fb-title {
  margin: 0 0 10px;
  font-size: 14px;
  color: #333;
}

.fb-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 10px;
}

.fb-radio {
  font-size: 13px;
  cursor: pointer;
}

.fb-field label {
  display: block;
  font-size: 13px;
  margin-bottom: 4px;
  color: #555;
}

.fb-textarea {
  width: 100%;
  box-sizing: border-box;
  font-size: 13px;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  resize: vertical;
}

.fb-field-err {
  margin: 6px 0 0;
  font-size: 12px;
  color: #c0392b;
}

.fb-actions {
  margin-top: 10px;
}

.fb-submit {
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid #3498db;
  background: #3498db;
  color: #fff;
  border-radius: 4px;
}

.fb-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.fb-success {
  margin: 10px 0 0;
  font-size: 13px;
  color: #1e8449;
}

.fb-error {
  margin-top: 10px;
}
</style>
