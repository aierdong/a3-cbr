# Brief: cbr-retrieval-recommendation

## Problem

门店和督导遇到新问题时，需要快速找到相似历史案例和可参考的解决步骤。只靠关键词搜索或普通 RAG chunk 检索，很难保留完整案例语境，也难回答“为什么这个案例值得参考”。

## Current State

`docs/product-overview.md` 描述了基于 CBR 的智能推送流程，包含结构化、查询改写、向量召回、语义重排、方案适配和推荐建议。`docs/mvp-product.md` 仅补充 MVP 阶段收敛：手动输入问题、Top-K 相似案例、推荐理由、相似度分值和基础过滤条件。

## Desired Outcome

用户输入新问题后，系统要先按品牌、门店、问题类型、标签、案例状态和时间范围等上游已支持条件过滤，再进行向量召回，并使用 Reranker（模型 id：`qwen3-reranker-8b`）对召回候选重排，返回 Top-K 相似案例。每条结果都要包含相似度、推荐理由、核心解决步骤和可追溯案例索引。

## Approach

检索推荐作为独立 CBR 规格，消费案例数据、LLM 派生内容和向量索引。CBRKit 作为可替换编排层，负责调用 `qwen3-reranker-8b` 完成候选重排并组装结果；核心查询契约、过滤字段、推荐结果结构由系统自身定义。

## Scope

- **In**: 查询输入标准化、基础过滤条件、Top-K 向量召回、`qwen3-reranker-8b` 重排、CBRKit 组装、相似度分值、推荐理由结构、原始案例引用、手动检索入口。
- **Out**: 自动推送渠道、经营指标触发、巡检触发、复杂多轮追问、反馈学习排序、行业库加权。

## Boundary Candidates

- 检索推荐消费向量索引，但不负责 embedding 写入。
- 推荐理由可由 LLM 生成，但排序和召回规则必须可追踪。
- CBRKit 只作为编排层，不拥有持久化数据模型。

## Out of Boundary

- App 内消息、邮件或客户成功代推等主动推送渠道。
- 行业库高权重召回。
- 根据反馈自动训练或调整召回权重。

## Upstream / Downstream

- **Upstream**: `a3-case-management`、`llm-case-enrichment`、`case-vector-indexing`。
- **Downstream**: `recommendation-feedback` 记录用户对推荐结果的反馈；`mvp-admin-frontend` 展示检索入口和推荐结果。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 与 `case-vector-indexing` 共享向量查询能力；与 `llm-case-enrichment` 共享推荐理由生成；与 `recommendation-feedback` 共享推荐结果标识。

## Constraints

推荐结果必须可解释、可追溯，不允许只返回黑盒文本。CBRKit 许可证为 MIT，但生态规模较小，设计上需要保留替换空间。
