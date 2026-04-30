# Research & Design Decisions

## Summary

- **Feature**: `llm-case-enrichment`
- **Discovery Scope**: Extension / Complex Integration
- **Key Findings**:
  - `a3-case-management` 已稳定基础案例契约。本规格以 `case_id`、基础字段、状态、过滤字段和更新时间为输入，不修改案例基础表及 CRUD 契约。
  - `docs/product-overview.md` 给出产品权威目标；`docs/mvp-product.md` 指定 MVP 阶段 LLM 使用 `deepseek-v4-pro`，用于摘要、结构化和推荐文案生成；LLM 不承担主检索职责。
  - 相邻规格边界清晰：`case-vector-indexing` 负责 embedding 和 pgvector，`cbr-retrieval-recommendation` 负责过滤、召回、重排和 Top-K 组装。本规格仅提供可校验的派生文本与推荐文案生成能力。

## Research Log

### 上游案例契约

- **Context**: 本规格依赖 `a3-case-management`，需避免反向改变基础案例边界。
- **Sources Consulted**: `.kiro/specs/a3-case-management/requirements.md`、`.kiro/specs/a3-case-management/design.md`、`.kiro/specs/a3-case-management/tasks.md`
- **Findings**:
  - 基础案例模型不包含摘要、向量、推荐理由或反馈字段。
  - 基础 API 暴露创建、编辑、详情、列表接口，保留 `case_id`、状态、过滤字段和更新时间。
  - 若下游字段或状态语义发生变化，需重新校验本规格的输入假设。
- **Implications**:
  - LLM 派生内容必须写入独立表或模块，不得写入 `a3_cases` 基础字段。
  - 重新生成判断应记录上游 `updated_at` 或等价的内容版本标识。
  - 输入有效性继承上游状态语义：仅 `active`、`archived` 可执行增强，`draft` 请求需拒绝并返回可识别的原因码。

### 产品与路线图边界

- **Context**: 确认 LLM 在 MVP 中的职责范围，不吸收检索或向量能力。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`
- **Findings**:
  - MVP 核心闭环涵盖案例入库、结构化、向量检索、推荐解释和反馈。
  - LLM 负责摘要、结构化提取和推荐结果生成，模型选用 `deepseek-v4-pro`。
  - roadmap 明确 LLM 输出必须经过结构化校验，并需覆盖隐私保护、供应商数据保留和提示词注入防护。
- **Implications**:
  - 设计应将 Prompt 组装、LLM 调用、输出校验和派生结果状态管理作为一条受控流水线。
  - 供应商配置缺失时，不得启用生产环境增强流程。

### 相邻规格边界

- **Context**: brief 明确本规格不得吸收向量索引或 CBR 检索职责。
- **Sources Consulted**: `.kiro/specs/case-vector-indexing/brief.md`、`.kiro/specs/cbr-retrieval-recommendation/brief.md`
- **Findings**:
  - 向量索引消费案例和 LLM 派生文本，负责 embedding 生成、pgvector 字段维护、索引状态管理和一致性保障。
  - CBR 推荐消费案例、LLM 派生内容和向量索引，负责查询标准化、过滤、Top-K 召回、reranker 重排和结果组装。
  - 推荐理由可由 LLM 生成，但排序和召回规则必须由检索推荐规格保持可追踪。
- **Implications**:
  - 本规格提供 `generate_recommendation_copy` 接口，不接收或返回排序决策。
  - 本规格可提供可索引的摘要和规范化文本，但不负责生成 embedding。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 案例模块内嵌 LLM 字段 | 在 `a3_cases` 中直接增加摘要和标签建议字段 | 实现成本最低 | 破坏上游基础契约，AI 派生内容与人工源数据混在一起 | Rejected |
| 独立 LLM 增强模块 | 通过 `case_id` 关联基础案例，独立保存派生结果、运行记录和状态 | 边界清晰，便于重试、审核和下游消费 | 需额外的表和服务编排 | Selected |
| 检索推荐内临时生成文案 | CBR 推荐流程内直接调用 LLM，不沉淀通用增强能力 | 推荐链路短 | 摘要、结构化提取和推荐文案重复实现，难以统一校验 | Rejected |

## Design Decisions

### Decision: 独立派生结果存储

- **Context**: LLM 输出需要可审核、可覆盖，不能直接替换用户原始输入。
- **Alternatives Considered**:
  1. 扩展 `a3_cases` 表保存摘要和标签建议。
  2. 使用独立的 `case_enrichment_results` 和 `case_enrichment_runs` 表分别保存结果和运行状态。
- **Selected Approach**: 采用独立派生结果表和运行记录表，通过 `case_id` 关联基础案例。
- **Rationale**: 保持 `a3-case-management` 契约稳定，同时支持输出版本管理、失败重试、审核流程和过期判断。
- **Trade-offs**: 查询下游派生内容需要额外 join，但数据边界和审计能力更清晰。
- **Follow-up**: 实施时确认是否需要为下游读取提供合并查询端点。

### Decision: Schema-first 输出校验

- **Context**: LLM 输出必须先通过结构化校验，再进入业务流程。
- **Alternatives Considered**:
  1. 直接保存 LLM 原始输出，由前端或下游自行解析。
  2. 通过 Pydantic schema 校验，仅发布通过校验的结构化结果。
- **Selected Approach**: Prompt 约定输出结构化 JSON，服务端使用 schema 校验字段类型、枚举值、长度限制、来源引用和安全边界。
- **Rationale**: 降低不可解析输出进入向量索引和推荐展示的风险。
- **Trade-offs**: 校验失败率可能上升，需明确失败记录和重试机制。
- **Follow-up**: 实施时用固定测试用例覆盖解析失败、字段缺失和标签越界等场景。

### Decision: 推荐文案只解释候选，不参与排序

- **Context**: CBR 推荐负责召回、过滤、排序和相似度计算，本规格只生成文案。
- **Alternatives Considered**:
  1. LLM 同时生成推荐理由并重新排列候选。
  2. LLM 仅消费已排序候选，生成解释文案和注意事项。
- **Selected Approach**: 推荐文案接口接收当前问题和已排序候选列表，返回每个候选的解释、参考点和注意事项，不返回排序变更。
- **Rationale**: 保持召回排序可追踪，避免黑盒文案干扰检索质量评估。
- **Trade-offs**: LLM 无法主动修正明显错误的排序；此类问题应交由 CBR 推荐规格处理。
- **Follow-up**: 推荐文案响应需保留候选 `case_id`，便于反馈和追溯。

### Decision: MVP 支持受控同步处理，保留异步运行记录

- **Context**: brief 要求定义同步或异步生成契约，LLM 调用可能超时或失败。
- **Alternatives Considered**:
  1. 仅实现同步接口。
  2. 仅实现异步队列。
  3. 使用运行记录抽象：MVP 同步执行，未来可接入后台 worker。
- **Selected Approach**: API 创建 enrichment run，MVP 在请求内同步完成或返回生成中状态；运行记录保存状态、错误和重试信息。
- **Rationale**: 不强制引入消息队列，同时不将接口锁死为纯同步模式。
- **Trade-offs**: 实施阶段需约定超时策略和轮询入口。
- **Follow-up**: 若后续引入 MQ，需重新校验运行状态和幂等语义。

## Risks & Mitigations

- **Prompt 注入导致输出越界** — 系统提示词固定输出 schema，忽略案例正文中的指令性文本，对输出字段执行白名单校验。
- **供应商失败影响主流程** — 运行记录标记失败及可重试状态，不阻塞案例基础查看和候选展示。
- **敏感门店或品牌信息泄露** — 限制输入范围，记录供应商数据保留配置，日志不保存完整提示词和案例正文。
- **下游误用未审核或失败结果** — 派生结果状态必须区分 `generating`、`validation_failed`、`pending_review`、`published`、`stale`、`failed`。
- **边界漂移到检索排序** — 推荐文案接口不得包含排序、相似度计算或召回控制字段。

## References

- `docs/mvp-product.md` — MVP 技术栈、LLM 角色与业务流程。
- `docs/product-overview.md` — 产品愿景与 A3+CBR 场景背景。
- `.kiro/steering/roadmap.md` — 规格拆分、依赖顺序与边界策略。
- `.kiro/specs/a3-case-management/design.md` — 上游案例基础契约。
- `.kiro/specs/case-vector-indexing/brief.md` — 向量索引边界。
- `.kiro/specs/cbr-retrieval-recommendation/brief.md` — CBR 推荐边界。
