/**
 * 任务 5.3：需求编号 → 测试文件登记（每项至少一个可执行测试文件存在）
 * 更新本表时请同步运行 `npm test`。
 */
import { describe, it, expect } from 'vitest'
import { existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

const COVERAGE: Record<string, string[]> = {
  '1.1': ['tests/router/index.test.ts', 'tests/components/layout/AdminLayout.test.ts'],
  '1.2': [
    'tests/router/index.test.ts',
    'tests/components/layout/AdminLayout.test.ts',
    'tests/pages/RecommendationPage.test.ts',
  ],
  '1.3': ['tests/components/layout/AdminLayout.test.ts'],
  '1.4': [
    'tests/api/client.test.ts',
    'tests/components/common/ErrorNotice.test.ts',
    'tests/composables/useAsyncState.test.ts',
  ],
  '1.5': ['tests/components/layout/AdminLayout.test.ts', 'tests/App.test.ts'],
  '2.1': ['tests/composables/useCaseList.test.ts', 'tests/pages/CaseListPage.test.ts'],
  '2.2': ['tests/composables/useCaseList.test.ts'],
  '2.3': ['tests/composables/useCaseList.test.ts', 'tests/pages/CaseListPage.test.ts'],
  '2.4': ['tests/components/cases/CaseDetailPanel.test.ts', 'tests/composables/useCaseDetail.test.ts'],
  '2.5': ['tests/components/cases/CaseDetailPanel.test.ts', 'tests/api/cases.test.ts'],
  '3.1': ['tests/components/cases/CaseForm.test.ts'],
  '3.2': ['tests/components/cases/CaseForm.test.ts'],
  '3.3': ['tests/components/cases/CaseForm.test.ts'],
  '3.4': ['tests/components/cases/CaseForm.test.ts'],
  '3.5': ['tests/components/cases/CaseForm.test.ts', 'tests/api/enrichment.test.ts'],
  '3.6': ['tests/components/cases/CaseForm.test.ts', 'tests/api/enrichment.test.ts'],
  '4.1': ['tests/components/recommendations/RecommendationSearchForm.test.ts'],
  '4.2': ['tests/components/recommendations/RecommendationSummary.test.ts', 'tests/pages/RecommendationPage.test.ts'],
  '4.3': ['tests/components/recommendations/RecommendationCard.test.ts'],
  '4.4': [
    'tests/components/recommendations/RecommendationSummary.test.ts',
    'tests/composables/useRecommendations.test.ts',
  ],
  '4.5': ['tests/composables/useRecommendations.test.ts', 'tests/api/recommendations.test.ts'],
  '5.1': ['tests/components/recommendations/FeedbackControls.test.ts', 'tests/pages/RecommendationPage.test.ts'],
  '5.2': ['tests/components/recommendations/FeedbackControls.test.ts'],
  '5.3': ['tests/components/recommendations/FeedbackControls.test.ts', 'tests/pages/RecommendationPage.test.ts'],
  '5.4': ['tests/components/recommendations/FeedbackControls.test.ts', 'tests/composables/useRecommendations.test.ts'],
  '5.5': ['tests/components/recommendations/FeedbackControls.test.ts'],
  '6.1': ['tests/api/cases.test.ts', 'tests/api/enrichment.test.ts', 'tests/api/recommendations.test.ts', 'tests/api/feedback.test.ts'],
  '6.2': [
    'tests/components/common/LoadingState.test.ts',
    'tests/components/common/EmptyState.test.ts',
    'tests/components/common/ErrorNotice.test.ts',
  ],
  '6.3': ['tests/api/cases.test.ts', 'tests/api/enrichment.test.ts', 'tests/api/recommendations.test.ts', 'tests/api/feedback.test.ts'],
  '6.4': ['tests/api/client.test.ts', 'tests/api/feedback.test.ts'],
  '6.5': ['tests/router/index.test.ts', 'tests/App.test.ts'],
}

describe('需求追溯登记（任务 5.3）', () => {
  it.each(Object.entries(COVERAGE))('需求 %s 登记的测试文件均存在', (_reqId, files) => {
    for (const rel of files) {
      expect(existsSync(join(ROOT, rel)), rel).toBe(true)
    }
  })
})
