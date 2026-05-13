<template>
  <form class="case-form" @submit.prevent>
    <template v-if="mode === 'edit' && initialDetail">
      <section class="readonly-block">
        <h3>只读信息</h3>
        <dl class="kv">
          <div>
            <dt>案例标识</dt>
            <dd>
              <span data-testid="readonly-case-id" class="mono">{{ initialDetail.case_id }}</span>
            </dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd>
              <span data-testid="readonly-created-at">{{ initialDetail.created_at }}</span>
            </dd>
          </div>
        </dl>
      </section>
    </template>

    <section class="field-block">
      <label for="pf-problem">问题描述 <span class="req">*</span></label>
      <textarea
        id="pf-problem"
        v-model="draft.problem_description"
        rows="4"
        data-testid="input-problem"
        :disabled="submitting"
      />
      <p v-if="fieldErrors?.problem_description" class="field-error">{{ fieldErrors.problem_description }}</p>
    </section>

    <section class="field-block">
      <label for="pf-store">门店标识 <span class="req">*</span></label>
      <input
        id="pf-store"
        v-model="draft.store_id"
        type="text"
        data-testid="input-store-id"
        :disabled="submitting"
      />
      <p v-if="fieldErrors?.store_id" class="field-error" data-testid="field-error-store_id">
        {{ fieldErrors.store_id }}
      </p>
    </section>

    <section class="field-block">
      <label for="pf-ptype">问题类型</label>
      <select
        id="pf-ptype"
        v-model="draft.problem_type"
        data-testid="select-problem-type"
        :disabled="submitting"
      >
        <option v-for="opt in CASE_PROBLEM_TYPE_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <p v-if="fieldErrors?.problem_type" class="field-error">{{ fieldErrors.problem_type }}</p>
    </section>

    <section class="field-block">
      <label for="pf-scene">场景上下文（场景）<span class="req">*</span></label>
      <textarea
        id="pf-scene"
        v-model="draft.scene"
        rows="1"
        data-testid="input-scene"
        :disabled="submitting"
      />
      <p v-if="fieldErrors?.['context.scene']" class="field-error">{{ fieldErrors['context.scene'] }}</p>
    </section>

    <section class="field-block">
      <label for="pf-root">根因分析 <span class="req">*</span></label>
      <textarea
        id="pf-root"
        v-model="draft.root_cause"
        rows="3"
        data-testid="input-root-cause"
        :disabled="submitting"
      />
      <p v-if="fieldErrors?.root_cause" class="field-error">{{ fieldErrors.root_cause }}</p>
    </section>

    <section class="field-block">
      <label for="pf-steps">解决步骤 <span class="req">*</span></label>
      <p class="field-hint">每行一个步骤；最多 20 步。提交时仍按接口要求的步骤列表上传。</p>
      <textarea
        id="pf-steps"
        v-model="solutionStepsText"
        rows="3"
        data-testid="input-solution-steps"
        :disabled="submitting"
      />
      <template v-for="item in solutionStepFieldErrors" :key="item.key">
        <p class="field-error">{{ item.label }}：{{ item.message }}</p>
      </template>
    </section>

    <section class="field-block">
      <label for="pf-outcome">效果结果</label>
      <select
        id="pf-outcome"
        v-model="draft.outcome.result"
        data-testid="select-outcome-result"
        :disabled="submitting"
      >
        <option v-for="opt in outcomeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <label for="pf-outcome-notes" class="inline-label">效果备注</label>
      <textarea
        id="pf-outcome-notes"
        v-model="draft.outcome.notes"
        rows="2"
        data-testid="input-outcome-notes"
        :disabled="submitting"
      />
      <p v-if="fieldErrors?.['outcome.notes']" class="field-error">{{ fieldErrors['outcome.notes'] }}</p>
    </section>

    <section class="field-block muted">
      <h4>标签</h4>
      <p>当前 API 契约不包含标签字段；无法在表单中保存标签。</p>
    </section>

    <div class="actions">
      <button
        type="button"
        class="btn-primary"
        data-testid="submit-with-summary"
        :disabled="submitting"
        @click="emitSubmit('submit-with-summary')"
      >
        提交且摘要
      </button>
      <button
        type="button"
        class="btn-secondary"
        data-testid="submit-save-and-close"
        :disabled="submitting"
        @click="emitSubmit('save-and-close')"
      >
        {{ mode === 'create' ? '创建并关闭' : '保存并关闭' }}
      </button>
      <button
        type="button"
        class="btn-secondary"
        data-testid="submit-save-draft"
        :disabled="submitting"
        @click="emitSubmit('save-draft')"
      >
        存为草稿
      </button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { CaseDetailResponse, CreateCaseRequest, UpdateCaseRequest } from '@/api/cases'
import { detailStore, type CaseDetailResponseApi } from '@/domain/caseListDisplay'
import { CASE_PROBLEM_TYPE_OPTIONS, type CaseProblemType } from '@/domain/caseProblemType'

type CaseStatus = CaseDetailResponse['status']

const props = withDefaults(
  defineProps<{
    mode: 'create' | 'edit'
    initialDetail?: CaseDetailResponse | null
    fieldErrors?: Record<string, string>
    submitting?: boolean
  }>(),
  {
    initialDetail: null,
    fieldErrors: () => ({}),
    submitting: false,
  }
)

export type CaseFormSubmitIntent = 'save-draft' | 'save-and-close' | 'submit-with-summary'

const emit = defineEmits<{
  submit: [payload: CreateCaseRequest | UpdateCaseRequest, meta: { intent: CaseFormSubmitIntent }]
}>()

const outcomeOptions = [
  { value: 'improved' as const, label: '改善' },
  { value: 'no_change' as const, label: '无变化' },
  { value: 'unknown' as const, label: '未知' },
]

interface Draft {
  problem_description: string
  store_id: string
  problem_type: CaseProblemType
  scene: string
  root_cause: string
  outcome: { result: CaseDetailResponse['outcome']['result']; notes: string }
  status: CaseStatus
}

function emptyDraft(): Draft {
  return {
    problem_description: '',
    store_id: '',
    problem_type: 'other',
    scene: '',
    root_cause: '',
    outcome: { result: 'unknown', notes: '' },
    status: 'draft',
  }
}

const draft = reactive<Draft>(emptyDraft())
/** 每行一步；提交时解析为 solution_steps 数组 */
const solutionStepsText = ref('')

function applyDetail(d: CaseDetailResponse): void {
  draft.problem_description = d.problem_description
  const s = detailStore(d as CaseDetailResponseApi)
  draft.store_id = s?.store_id ?? ''
  draft.problem_type = d.problem_type
  draft.scene = d.context.scene
  draft.root_cause = d.root_cause
  solutionStepsText.value =
    d.solution_steps.length > 0
      ? [...d.solution_steps].sort((a, b) => a.order - b.order).map((s) => s.content).join('\n')
      : ''
  draft.outcome = { result: d.outcome.result, notes: d.outcome.notes ?? '' }
  draft.status = d.status
}

function resetCreateDraft(): void {
  const e = emptyDraft()
  draft.problem_description = e.problem_description
  draft.store_id = e.store_id
  draft.problem_type = e.problem_type
  draft.scene = e.scene
  draft.root_cause = e.root_cause
  solutionStepsText.value = ''
  draft.outcome.result = e.outcome.result
  draft.outcome.notes = e.outcome.notes
  draft.status = e.status
}

watch(
  () => [props.mode, props.initialDetail] as const,
  ([mode, det]) => {
    if (mode === 'edit') {
      if (det) applyDetail(det)
      return
    }
    resetCreateDraft()
  },
  { immediate: true }
)

/** 与提交逻辑一致：按行解析，去掉行尾空行，每行 trim，最多 20 步；全空则一步空串 */
function parseSolutionStepsFromText(text: string): { order: number; content: string }[] {
  let lines = text.split('\n').map((line) => line.trim())
  while (lines.length > 1 && lines[lines.length - 1] === '') {
    lines.pop()
  }
  if (lines.length === 0) lines = ['']
  lines = lines.slice(0, 20)
  return lines.map((content, i) => ({ order: i + 1, content }))
}

const solutionStepFieldErrors = computed(() => {
  const fe = props.fieldErrors
  if (!fe) return []
  const out: { key: string; idx: number; label: string; message: string }[] = []
  for (const [k, v] of Object.entries(fe)) {
    const m = /^solution_steps\.(\d+)\.content$/.exec(k)
    if (m && v) {
      const idx = Number(m[1])
      out.push({ key: k, idx, label: `第 ${idx + 1} 步`, message: v })
    }
  }
  out.sort((a, b) => a.idx - b.idx)
  return out.map(({ key, label, message }) => ({ key, label, message }))
})

function emitSubmit(intent: CaseFormSubmitIntent): void {
  const steps = parseSolutionStepsFromText(solutionStepsText.value)
  const context: CaseDetailResponse['context'] = { scene: draft.scene.trim() }
  const targetStatus = intent === 'save-draft' ? 'draft' : 'active'
  if (props.mode === 'create') {
    const body: CreateCaseRequest = {
      problem_description: draft.problem_description.trim(),
      store_id: draft.store_id.trim(),
      problem_type: draft.problem_type,
      context,
      root_cause: draft.root_cause.trim(),
      solution_steps: steps,
      outcome: {
        result: draft.outcome.result,
        notes: draft.outcome.notes.trim(),
      },
      status: targetStatus,
    }
    emit('submit', body, { intent })
    return
  }
  const body: UpdateCaseRequest = {
    problem_description: draft.problem_description.trim(),
    store_id: draft.store_id.trim(),
    problem_type: draft.problem_type,
    context,
    root_cause: draft.root_cause.trim(),
    solution_steps: steps,
    outcome: {
      result: draft.outcome.result,
      notes: draft.outcome.notes.trim(),
    },
    status: targetStatus,
  }
  emit('submit', body, { intent })
}
</script>

<style scoped>
.case-form {
  max-width: 720px;
}

.readonly-block {
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #f9f9f9;
  border-radius: 6px;
  border: 1px solid #eee;
}

.readonly-block h3 {
  margin: 0 0 8px;
  font-size: 15px;
}

.field-block {
  margin-bottom: 16px;
}

.field-block label {
  display: block;
  margin-bottom: 6px;
  font-weight: 500;
}

.inline-label {
  margin-top: 10px;
}

input[type='text'],
textarea,
select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #ccc;
  border-radius: 4px;
}

.req {
  color: #c62828;
}

.field-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: #c62828;
}

.field-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: #666;
}

.btn-primary {
  padding: 10px 20px;
  background: #1976d2;
  color: #fff;
  border-radius: 4px;
  border: none;
  cursor: pointer;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.actions {
  margin-top: 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.btn-secondary {
  padding: 10px 20px;
  background: #fff;
  color: #333;
  border-radius: 4px;
  border: 1px solid #bbb;
  cursor: pointer;
}

.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.kv > div {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 8px;
  margin-bottom: 6px;
}

dt {
  color: #666;
}

dd {
  margin: 0;
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.muted {
  font-size: 13px;
  color: #666;
}

.muted h4 {
  margin: 0 0 6px;
}
</style>
