/**
 * 推荐反馈提交用例（design.md § useFeedback；tasks 4.2–4.3）
 * 仅封装提交与错误映射，不修改推荐列表或排序。
 */

import {
  feedbackControlStateFromApiError,
  type FeedbackApiService,
  type FeedbackControlErrorState,
  type FeedbackResponse,
  type FeedbackSubmitInput,
} from '../api/feedback'

export type FeedbackSubmitResult =
  | { ok: true; data: FeedbackResponse }
  | { ok: false; control: FeedbackControlErrorState }

export function useFeedbackSubmit(api: FeedbackApiService) {
  async function submit(input: FeedbackSubmitInput): Promise<FeedbackSubmitResult> {
    const res = await api.submit(input)
    if (!res.ok) {
      return { ok: false, control: feedbackControlStateFromApiError(res.error) }
    }
    return { ok: true, data: res.data }
  }

  return { submit }
}
