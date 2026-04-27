# Roadmap

## Overview

这个 MVP 面向门店和督导的 A3 辅导场景，先验证“案例入库、结构化、向量检索、相似案例推荐、基础反馈”这条最小闭环。产品愿景以 `docs/product-overview.md` 为准，当前交付边界以 `docs/mvp-product.md` 为准。

MVP 走独立产品路线，先搭建 Python + FastAPI 后端、Vue 3 基础后台、PostgreSQL + pgvector 数据层，以及 CBRKit + 云端 embedding + LLM 的检索推荐链路。当前优先保证四件事：案例结构化、语义召回、推荐可解释、反馈可记录。经营数据、巡检、行业库等复杂集成暂不纳入。

## Approach Decision

- **Chosen**: 领域边界拆分。将 MVP 拆为案例管理、LLM 增强、向量索引、CBR 检索推荐、反馈闭环、前端后台 6 个规格。
- **Why**: MVP 同时覆盖数据模型、AI 编排、向量检索、推荐解释、反馈和页面交互。若只写一个规格，范围会过大。按领域拆分后，需求、设计、任务和评审边界更清楚，也更适合并行推进。
- **Rejected alternatives**: 单一 MVP spec 会混在一起处理后端、前端、AI 和检索职责；按垂直闭环拆分虽然更贴近交付节奏，但会在多个 spec 里重复定义同一数据模型和检索边界。

## Scope

- **In**: A3 案例创建、编辑、查询；案例字段结构化存储；摘要、标签和推荐理由生成；云端 embedding 生成；PostgreSQL + pgvector 存储与检索；CBRKit 召回结果重排与组装；Top-K 相似案例推荐；基础反馈记录；Vue 3 基础后台页面。
- **Out**: 巡检报告自动触发、经营指标阈值自动触发、MQ 事件集成、行业知识库聚合、跨品牌脱敏流程、经营数据看板、SOP/训练模块深度联动、复杂权限体系、复杂学习排序。

## Constraints

- 后端采用 Python + FastAPI，前端采用 Vue 3。
- 数据层采用 PostgreSQL + pgvector，pgvector 版本需锁定到 `0.8.2+`。
- embedding 通过云端 API 使用远程服务，默认使用 BGE-M3；若 BGE-M3 服务不可行，再评估 `text-embedding-v4`、`qwen-embedding-v1` 等云端替代方案。
- CBRKit 作为可替换的案例推理编排层，核心数据模型和持久化设计不能与其强绑定。
- LLM 用于摘要、结构化提取、标签建议和推荐文案生成，不承担主检索职责。
- LLM 输出必须经过结构化校验。涉及门店、品牌和案例内容时，要在后续规格里明确数据隐私、供应商数据保留策略和提示词注入防护要求。

## Boundary Strategy

- **Why this split**: 案例数据是底座。LLM 增强、向量索引和 CBR 检索各自承担不同技术职责；反馈闭环依赖推荐结果，但不能阻塞核心检索；前端后台负责消费后端能力，并提供 MVP 验证入口。
- **Shared seams to watch**: 重点关注这些共享边界：案例字段契约、案例状态流转、embedding 输入文本拼接策略、检索过滤字段、推荐结果解释结构、反馈记录与检索日志的关联关系。

## Specs (dependency order)

- [ ] a3-case-management -- 定义 A3 案例数据模型、基础校验、创建/编辑/详情/列表查询 API。Dependencies: none
- [ ] llm-case-enrichment -- 为案例和检索结果提供摘要、结构化提取、标签建议和推荐文案能力。Dependencies: a3-case-management
- [ ] case-vector-indexing -- 通过云端 embedding API 生成向量，并使用 PostgreSQL + pgvector 管理案例向量索引。Dependencies: a3-case-management, llm-case-enrichment
- [ ] cbr-retrieval-recommendation -- 基于结构化过滤、向量召回和 CBRKit 重排组装返回相似案例与推荐解释。Dependencies: a3-case-management, llm-case-enrichment, case-vector-indexing
- [ ] recommendation-feedback -- 记录推荐结果的有用/无用、评分、采纳状态和查询命中关系。Dependencies: cbr-retrieval-recommendation
- [ ] mvp-admin-frontend -- 提供 Vue 3 基础后台页面，覆盖案例管理、检索推荐展示和反馈控件。Dependencies: a3-case-management, cbr-retrieval-recommendation, recommendation-feedback
