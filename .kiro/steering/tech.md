# Technology Stack

updated_at: 2026-04-28

## Architecture

系统采用“应用层 + 检索层 + 数据层”的三层结构。

- **应用层**：前端页面与后端 API，负责案例管理、检索入口、推荐展示和反馈记录。
- **检索层**：负责案例推理编排，结合结构化过滤、向量召回、重排和结果组装。
- **数据层**：使用 PostgreSQL + pgvector 同时保存业务案例数据、向量索引、检索日志和反馈记录。

MVP 作为独立产品研发，通过 API 与现有慧运营能力集成；复杂事件监听、MQ 推送、巡检自动触发、行业库聚合等能力放在后续阶段。

## Core Technologies

- **Backend**：Python + FastAPI。
- **Frontend**：Vue 3。
- **Database**：PostgreSQL + pgvector，pgvector 版本要求 `0.8.2+`。
- **Embedding**：云端 BGE-M3，模型接入点 `bge-large-zh`。
- **Reranker**：云端 Qwen3-Reranker-8B，模型接入点 `qwen3-reranker-8b`。
- **LLM**：DeepSeek 兼容 OpenAI API 的接入方式，MVP 文档中指定 `deepseek-v4-flash`。

## Key Technical Decisions

- **单库优先**：MVP 采用 PostgreSQL + pgvector 一体化部署，减少部署复杂度，并保证案例数据与向量索引的一致性。
- **结构化字段与向量检索并行**：结构化字段用于过滤和权限/范围控制，向量检索用于语义召回，两者都不能省略。
- **LLM 不做主检索**：LLM 用于摘要、结构化提取、标签建议、问题标准化和推荐解释，不直接替代向量召回与 CBR 排序。
- **案例推理编排**：检索层负责候选集内的相似度计算、加权聚合和排序决策；案例数据模型和持久化设计不与检索编排实现强绑定，保持清晰的适配边界。
- **推荐必须可解释**：检索返回需要包含相似案例、推荐理由、相似度分值和必要的原始案例索引，避免纯黑盒建议。
- **MVP 避免过度设计**：复杂规则引擎、多轮 Agent、训练平台、离线特征工程和跨系统双写不进入当前技术边界。

## Development Standards

### API and Data Contracts

后端 API 应围绕领域边界组织：案例管理、LLM 增强、向量索引、案例检索推荐、反馈记录和后台页面消费。共享契约需要优先稳定，特别是案例字段、案例状态、embedding 输入文本、检索过滤字段、推荐解释结构、反馈记录与检索日志之间的关联。

### AI Output Safety

LLM 输出必须经过结构化校验后才能进入业务流程。涉及门店、品牌、案例内容和行业库候选时，需要关注数据隐私、供应商数据保留策略、提示词注入防护和脱敏边界。

### Retrieval Quality

检索链路应保留可观察信息，包括查询文本、标准化结果、过滤条件、召回案例、重排结果、推荐解释和用户反馈。反馈数据用于后续评估召回质量和排序优化，但不能阻塞 MVP 的核心检索闭环。

### Python Readability Constraints

以下约束在后续 `backend` Python 代码落地后生效，作为默认工程标准：

1. 所有 public 级别函数必须包含结构化 docstring，最少覆盖：
   - 函数作用（Summary）
   - 输入参数（Args）
   - 输出参数（Returns）
   - 异常说明（Raises，若函数无显式抛出可省略）
2. 每个 Python 文件应聚焦单一类或单一功能，避免将多个不相关职责混合在同一模块。
3. 函数长度默认不超过 100 行；仅在以下情况允许例外：
   - 大量顺序赋值语句导致行数增长；
   - 方法参数较多且因可读性分行导致行数增长。

长度例外必须在函数定义前使用注释标签声明原因：
- `# readability-exception: bulk-assignment`
- `# readability-exception: long-signature`

当模块职责边界无法静态精确判定时，优先按“同一业务职责域”组织，并在 Code Review 中确认边界合理性。

## Development Environment

当前仓库以产品文档、规格文档和 steering 为主，尚未发现后端或前端脚手架配置。具体运行、构建和测试命令应在对应脚手架落地后补充到本文件；在此之前，以 `docs/` 和 `.kiro/specs/` 中的已批准设计作为实现依据。

---
_记录影响开发决策的技术原则，不维护依赖清单或安装手册。_
