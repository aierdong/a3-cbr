# Brief: llm-case-enrichment

## Problem

A3 案例通常包含较长的自然语言描述、根因分析和解决步骤。只靠人工录入，摘要、标签和推荐说明很容易不一致，进而影响案例归集、检索展示和推荐解释。

## Current State

`docs/product-overview.md` 定义了 A3+CBR 的产品主线；`docs/mvp-product.md` 在 MVP 阶段补充 LLM 用于摘要、结构化提取和推荐结果生成，但不承担主检索职责。当前尚未定义 LLM 的编排边界、结构化输出约束和失败处理策略。

## Desired Outcome

系统要能基于 A3 案例内容生成问题摘要、方案摘要、标签建议和必要的结构化字段建议，并为相似案例推荐生成可解释文案。LLM 输出必须先通过结构化校验，再进入业务流程。

## Approach

LLM 能力抽成独立规格，作为案例管理、向量索引和推荐展示之间的弱耦合增强层。MVP 先定义同步或异步生成的接口契约、输出格式、校验规则和失败降级机制，不把 LLM 绑定为检索核心。

## Scope

- **In**: 案例摘要、方案摘要、问题类型和标签建议、推荐理由文案、结构化输出 schema、输出校验、失败记录和重试边界。
- **Out**: 向量检索、CBRKit 重排、案例 CRUD、反馈评分学习、模型微调、本地大模型部署。

## Boundary Candidates

- LLM 派生内容与人工录入的源案例内容分离。
- 结构化提取结果需要可审核、可覆盖，不直接替换用户原始输入。
- 推荐理由生成消费检索结果，不决定召回排序。

## Out of Boundary

- 将 LLM 作为主检索引擎。
- 复杂多轮追问补全流程。
- 针对供应商的深度模型训练或私有化部署。

## Upstream / Downstream

- **Upstream**: `a3-case-management`。
- **Downstream**: `case-vector-indexing` 使用摘要或规范化文本作为向量输入；`cbr-retrieval-recommendation` 使用推荐理由；`mvp-admin-frontend` 展示 LLM 派生内容。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 与 `case-vector-indexing` 共享文本拼接和摘要字段边界；与 `cbr-retrieval-recommendation` 共享推荐解释结构。

## Constraints

LLM 服务供应商需要支持结构化输出或可解析文本输出。规格中应记录数据隐私、供应商数据保留策略、提示词注入防护和输出 schema 校验要求。
