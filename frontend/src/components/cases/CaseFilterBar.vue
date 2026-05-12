<template>
  <section class="case-filter-bar" aria-label="案例列表筛选">
    <div class="filter-grid">
      <label class="field">
        <span class="label">品牌 ID</span>
        <input v-model.trim="draft.brand_id" type="text" autocomplete="off" placeholder="brand_id" />
      </label>
      <label class="field">
        <span class="label">门店 ID</span>
        <input v-model.trim="draft.store_id" type="text" autocomplete="off" placeholder="store_id" />
      </label>
      <label class="field">
        <span class="label">问题类型</span>
        <select v-model="problemTypeModel">
          <option value="">全部</option>
          <option v-for="opt in problemTypeOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </label>
      <label class="field">
        <span class="label">状态</span>
        <select v-model="statusModel">
          <option value="">全部</option>
          <option value="draft">草稿</option>
          <option value="active">生效</option>
          <option value="archived">归档</option>
        </select>
      </label>
      <label class="field wide">
        <span class="label">标签关键词（逗号分隔）</span>
        <input
          v-model.trim="draft.tags"
          type="text"
          autocomplete="off"
          placeholder="例如：客诉, 卫生"
          title="在当前已加载结果中按标签或预览文本筛选；服务端标签筛选待契约扩展后接入"
        />
      </label>
      <label class="field">
        <span class="label">创建时间起（含）</span>
        <input v-model="createdFromLocal" type="datetime-local" />
      </label>
      <label class="field">
        <span class="label">创建时间止（含）</span>
        <input v-model="createdToLocal" type="datetime-local" />
      </label>
      <label class="field checkbox-field">
        <input v-model="draft.include_archived" type="checkbox" />
        <span class="label inline">包含归档案例</span>
      </label>
    </div>
    <div class="actions">
      <button type="button" class="btn primary" data-testid="filter-submit" @click="submit">查询</button>
      <button type="button" class="btn" data-testid="filter-reset" @click="reset">重置</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { CaseListFilters } from '@/composables/useCases'

const props = defineProps<{
  /** 与父级同步的筛选（例如重载后回显） */
  modelValue: CaseListFilters
}>()

const emit = defineEmits<{
  'update:modelValue': [value: CaseListFilters]
  submit: [value: CaseListFilters]
}>()

const problemTypeOptions = [
  { value: 'service', label: '服务' },
  { value: 'quality', label: '质量' },
  { value: 'operation', label: '运营' },
  { value: 'hygiene', label: '卫生' },
  { value: 'staffing', label: '人力' },
  { value: 'other', label: '其他' },
] as const

const draft = reactive<CaseListFilters>({ ...emptyFilters(), ...props.modelValue })

const createdFromLocal = ref(isoToLocalDatetime(props.modelValue.created_from))
const createdToLocal = ref(isoToLocalDatetime(props.modelValue.created_to))

function emptyFilters(): CaseListFilters {
  return {
    brand_id: '',
    store_id: '',
    problem_type: undefined,
    status: undefined,
    tags: '',
    created_from: undefined,
    created_to: undefined,
    include_archived: false,
  }
}

function isoToLocalDatetime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  const y = d.getFullYear()
  const m = pad(d.getMonth() + 1)
  const day = pad(d.getDate())
  const h = pad(d.getHours())
  const min = pad(d.getMinutes())
  return `${y}-${m}-${day}T${h}:${min}`
}

function localDateToIso(local: string): string | undefined {
  if (!local) return undefined
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return undefined
  return d.toISOString()
}

const problemTypeModel = computed({
  get: () => draft.problem_type ?? '',
  set: (v: string) => {
    draft.problem_type = v ? (v as CaseListFilters['problem_type']) : undefined
  },
})

const statusModel = computed({
  get: () => draft.status ?? '',
  set: (v: string) => {
    draft.status = v ? (v as CaseListFilters['status']) : undefined
  },
})

watch(
  () => props.modelValue,
  (v) => {
    Object.assign(draft, emptyFilters(), v)
    createdFromLocal.value = isoToLocalDatetime(v.created_from)
    createdToLocal.value = isoToLocalDatetime(v.created_to)
  },
  { deep: true }
)

function buildPayload(): CaseListFilters {
  return {
    ...draft,
    brand_id: draft.brand_id || undefined,
    store_id: draft.store_id || undefined,
    tags: draft.tags || undefined,
    created_from: localDateToIso(createdFromLocal.value),
    created_to: localDateToIso(createdToLocal.value),
    include_archived: draft.include_archived === true ? true : undefined,
  }
}

function submit(): void {
  const payload = buildPayload()
  emit('update:modelValue', payload)
  emit('submit', payload)
}

function reset(): void {
  Object.assign(draft, emptyFilters())
  createdFromLocal.value = ''
  createdToLocal.value = ''
  const payload = buildPayload()
  emit('update:modelValue', payload)
  emit('submit', payload)
}
</script>

<style scoped>
.case-filter-bar {
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
  align-items: end;
}

.field.wide {
  grid-column: 1 / -1;
}

.field.checkbox-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.label {
  display: block;
  font-size: 12px;
  color: #555;
  margin-bottom: 4px;
}

.label.inline {
  margin-bottom: 0;
}

.field input[type='text'],
.field select,
.field input[type='datetime-local'] {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-sizing: border-box;
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
</style>
