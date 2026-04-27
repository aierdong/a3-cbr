# Brief: case-vector-indexing

## Problem

相似案例推荐依赖语义召回。只存结构化字段，系统就处理不了口语化、非结构化的新问题描述，也识别不出不同说法下的同类经营问题。

## Current State

`docs/product-overview.md` 建议使用 BGE-M3 和 pgvector，`docs/mvp-product.md` 明确使用 PostgreSQL + pgvector 保存案例、向量和反馈。当前方案已确定：BGE-M3 通过云端 API 远程调用，不纳入本地部署成本。若 BGE-M3 服务不可行，再评估 `text-embedding-v4`、`qwen-embedding-v1` 等云端替代方案。

## Desired Outcome

系统在案例创建或更新后，要稳定生成 embedding，并将向量和结构化字段一起写入 PostgreSQL + pgvector。案例发生修改、删除或状态变化时，向量索引要保持一致，以支撑后续 Top-K 语义召回。

## Approach

本规格单独定义向量索引，覆盖 embedding 输入文本、远程 embedding API 适配、向量字段、pgvector 索引、更新/删除一致性和错误处理。MVP 优先单库部署，不引入独立向量数据库。

## Scope

- **In**: embedding 输入文本策略、云端 embedding API 调用、BGE-M3 默认适配、云端替代方案评估边界、pgvector 字段和索引、案例向量创建/更新/删除、索引状态记录。
- **Out**: CBRKit 重排、推荐理由生成、反馈学习排序、Milvus 等独立向量库、模型本地部署和推理成本优化。

## Boundary Candidates

- 向量索引消费案例和 LLM 派生文本，但不拥有案例业务字段。
- embedding 服务适配层需要屏蔽具体供应商差异。
- 索引状态与案例状态关联，但不改变案例的业务生命周期。

## Out of Boundary

- 百万级以上独立向量库架构。
- 多模型融合召回。
- 离线批量训练或私有化模型部署。

## Upstream / Downstream

- **Upstream**: `a3-case-management`、`llm-case-enrichment`。
- **Downstream**: `cbr-retrieval-recommendation` 使用向量索引做 Top-K 召回；`mvp-admin-frontend` 可展示案例可检索状态。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 与 `llm-case-enrichment` 共享摘要和规范化文本；与 `cbr-retrieval-recommendation` 共享向量查询和过滤字段。

## Constraints

PostgreSQL 必须启用 pgvector，版本锁定到 `0.8.2+`。embedding 默认使用 BGE-M3 云端远程服务；若服务不可用，再评估 `text-embedding-v4`、`qwen-embedding-v1` 等云端模型，同时关注向量维度、归一化方式、限流、超时和重试策略。
