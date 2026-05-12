<template>
  <form class="case-form" @submit.prevent="onSubmit">
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
        <option v-for="opt in problemOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <p v-if="fieldErrors?.problem_type" class="field-error">{{ fieldErrors.problem_type }}</p>
    </section>

    <section class="field-block">
      <label for="pf-scene">场景上下文（场景）<span class="req">*</span></label>
      <textarea
        id="pf-scene"
        v-model="draft.scene"
        rows="3"
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
      <div class="steps-head">
        <label>解决步骤 <span class="req">*</span></label>
        <button
          v-if="draft.solution_steps.length < 20"
          type="button"
          class="btn-ghost"
          :disabled="submitting"
          @click="addStep"
        >
          添加步骤
        </button>
      </div>
      <div v-for="(step, idx) in draft.solution_steps" :key="idx" class="step-row">
        <span class="step-label">步骤 {{ idx + 1 }}</span>
        <textarea
          v-model="step.content"
          rows="2"
          :data-testid="'input-step-' + idx"
          :disabled="submitting"
        />
        <button
          v-if="draft.solution_steps.length > 1"
          type="button"
          class="btn-ghost"
          :disabled="submitting"
          @click="removeStep(idx)"
        >
          删除
        </button>
        <p v-if="fieldErrors?.[stepErrorKey(idx)]" class="field-error">{{ fieldErrors[stepErrorKey(idx)] }}</p>
      </div>
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

    <section v-if="mode === 'edit'" class="field-block">
      <label for="pf-status">案例状态</label>
      <select id="pf-status" v-model="draft.status" data-testid="select-status" :disabled="submitting">
        <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <p v-if="fieldErrors?.status" class="field-error">{{ fieldErrors.status }}</p>
    </section>

    <section class="field-block muted">
      <h4>标签</h4>
      <p>当前 API 契约不包含标签字段；无法在表单中保存标签。</p>
    </section>

    <div class="actions">
      <button type="submit" class="btn-primary" data-testid="submit-form" :disabled="submitting">
        {{ mode === 'create' ? '创建案例' : '保存修改' }}
      </button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { CaseDetailResponse, CreateCaseRequest, UpdateCaseRequest } from '@/api/cases'

type ProblemType = CaseDetailResponse['problem_type']
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

const emit = defineEmits<{
  submit: [payload: CreateCaseRequest | UpdateCaseRequest]
}>()

const problemOptions: { value: ProblemType; label: string }[] = [
  { value: 'service', label: '服务' },
  { value: 'quality', label: '质量' },
  { value: 'operation', label: '运营' },
  { value: 'hygiene', label: '卫生' },
  { value: 'staffing', label: '人力' },
  { value: 'other', label: '其他' },
]

const outcomeOptions = [
  { value: 'improved' as const, label: '改善' },
  { value: 'no_change' as const, label: '无变化' },
  { value: 'unknown' as const, label: '未知' },
]

const statusOptions: { value: CaseStatus; label: string }[] = [
  { value: 'draft', label: '草稿' },
  { value: 'active', label: '生效' },
  { value: 'archived', label: '归档' },
]

interface Draft {
  problem_description: string
  store_id: string
  problem_type: ProblemType
  scene: string
  root_cause: string
  solution_steps: { order: number; content: string }[]
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
    solution_steps: [{ order: 1, content: '' }],
    outcome: { result: 'unknown', notes: '' },
    status: 'draft',
  }
}

const draft = reactive<Draft>(emptyDraft())

function applyDetail(d: CaseDetailResponse): void {
  draft.problem_description = d.problem_description
  draft.store_id = d.store_profile.store_id
  draft.problem_type = d.problem_type
  draft.scene = d.context.scene
  draft.root_cause = d.root_cause
  draft.solution_steps = d.solution_steps.map((s) => ({ order: s.order, content: s.content }))
  if (draft.solution_steps.length === 0) draft.solution_steps = [{ order: 1, content: '' }]
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
  draft.solution_steps.splice(0, draft.solution_steps.length, ...e.solution_steps.map((s) => ({ ...s })))
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

function stepErrorKey(idx: number): string {
  return `solution_steps.${idx}.content`
}

function addStep(): void {
  const next = draft.solution_steps.length + 1
  draft.solution_steps.push({ order: next, content: '' })
}

function removeStep(idx: number): void {
  if (draft.solution_steps.length <= 1) return
  draft.solution_steps.splice(idx, 1)
}

function onSubmit(): void {
  const steps = draft.solution_steps.map((s, i) => ({
    order: i + 1,
    content: s.content.trim(),
  }))
  const context: CaseDetailResponse['context'] = { scene: draft.scene.trim() }
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
    }
    emit('submit', body)
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
    status: draft.status,
  }
  emit('submit', body)
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

.steps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.step-row {
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid #eee;
  border-radius: 4px;
}

.step-label {
  display: block;
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.btn-ghost {
  padding: 4px 10px;
  border: 1px solid #bbb;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
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
