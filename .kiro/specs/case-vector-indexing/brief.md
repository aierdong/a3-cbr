# Brief: case-vector-indexing

## Problem

相似案例推荐依赖语义召回。当前系统仅存储结构化字段，无法处理口语化、非结构化的新问题描述，也难以识别不同表述下的同类经营问题。

## Current State

通过云端 API 远程调用 BGE-M3（模型 ID: bge-large-zh）实现向量化，使用本地 pgvector 作为向量数据库。

## Desired Outcome

案例创建或更新后，系统需稳定生成问题侧 embedding，并将向量与结构化字段一并写入 PostgreSQL + pgvector。当案例发生修改、删除或状态变化时，向量索引需保持一致，以支撑后续 Top-K 问题语义召回。

## Approach

本规格单独定义向量索引，覆盖以下内容：问题侧 embedding 输入文本策略、远程 embedding API 适配、向量字段、pgvector 索引、更新/删除一致性保障和错误处理。MVP 阶段优先单库部署，不引入独立向量数据库。

## Scope

- **In**: 问题侧 embedding 输入文本策略、云端 embedding API 调用、BGE-M3（模型 ID: bge-large-zh）默认适配、云端替代方案评估边界、pgvector 字段和索引、案例问题向量创建/更新/删除、索引状态记录。
- **Out**: CBRKit 重排、推荐理由生成、反馈学习排序、Milvus 等独立向量库、模型本地部署及推理成本优化。

## Boundary Candidates

- 向量索引消费案例问题字段和 LLM 问题侧派生文本，但不拥有案例业务字段。
- embedding 服务适配层屏蔽具体供应商差异。
- 索引状态与案例状态关联，但不改变案例的业务生命周期。

## Out of Boundary

- 百万级以上独立向量库架构。
- 多模型融合召回。
- 离线批量训练或私有化模型部署。

## Upstream / Downstream

- **Upstream**: `a3-case-management`、`llm-case-enrichment`。
- **Downstream**: `cbr-retrieval-recommendation` 使用向量索引进行 Top-K 召回；`mvp-admin-frontend` 可展示案例可检索状态。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 与 `llm-case-enrichment` 共享摘要和规范化文本；与 `cbr-retrieval-recommendation` 共享向量查询和过滤字段。

## Constraints

PostgreSQL 必须启用 pgvector，版本锁定至 `0.8.2+`。embedding 默认使用 BGE-M3（模型 ID: bge-large-zh）云端远程服务。
