# Brief: a3-case-management

## Problem

门店和督导需要按标准 A3 流程记录经营辅导问题。当前仓库还没有可落地的数据模型、API 和页面契约。缺少这套结构化案例底座，后续的 LLM 增强、向量索引、CBR 推荐和反馈流程都难以稳定落地。

## Current State

`docs/product-overview.md` 已定义 A3 标准步骤和知识沉淀目标，`docs/mvp-product.md` 已明确案例创建、编辑、查询以及结构化字段要求。仓库目前没有应用代码和既有规格，第一步需要先补齐案例域基础契约。

## Desired Outcome

系统能够创建、编辑、查看和查询 A3 案例，并用结构化字段保存问题、门店/品牌、问题类型、上下文、根因、解决步骤、效果、标签和创建时间。案例数据要作为后续 AI 增强、向量索引、检索推荐和前端页面的统一基础。

## Approach

先定义独立的 A3 案例管理规格，聚焦数据模型、字段校验、状态、基础 CRUD API 和列表查询能力。本规格不处理 LLM、embedding、CBR 或反馈逻辑，只负责提供稳定的案例数据边界。

## Scope

- **In**: A3 案例实体、必填字段、基础校验、创建、编辑、详情、列表查询、基础状态字段、后续索引与推荐所需的稳定标识。
- **Out**: LLM 自动摘要与结构化提取、向量生成、相似案例检索、推荐解释、反馈记录、复杂权限、经营数据自动拉取。

## Boundary Candidates

- 案例基础数据与 AI 派生字段分离。
- 案例 CRUD API 与检索推荐 API 分离。
- 案例状态只表达 MVP 所需的基础可用性，不提前承接完整知识库发布审核流。

## Out of Boundary

- 巡检报告或经营指标自动创建案例。
- 行业库入库审核、跨品牌脱敏和质量评分体系。
- 与慧运营人员、SOP、训练模块的深度集成。

## Upstream / Downstream

- **Upstream**: `docs/product-overview.md`、`docs/mvp-product.md`。
- **Downstream**: `llm-case-enrichment`、`case-vector-indexing`、`cbr-retrieval-recommendation`、`recommendation-feedback`、`mvp-admin-frontend`。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 后续 LLM、向量索引、CBR 检索和前端后台规格都依赖本规格定义的数据契约。

## Constraints

案例模型要同时支持结构化过滤和语义检索输入。字段命名、状态和标识需要保持稳定，避免后续规格反复重写基础契约。
