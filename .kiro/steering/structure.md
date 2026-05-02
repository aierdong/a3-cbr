# Project Structure

updated_at: 2026-04-28

## Organization Philosophy

项目采用文档优先、规格驱动的组织方式。当前权威顺序为 `docs/*.md` > `.kiro/specs/` > `.kiro/steering/` > 现有代码。产品文档定义方向和边界，规格文档承接需求、设计和任务拆分，steering 记录长期稳定的项目记忆。

实现层面按领域边界拆分，而不是把所有 MVP 能力放进一个大模块。案例管理是底座，LLM 增强、向量索引、案例检索推荐、反馈闭环和前端后台围绕它分层协作。

## Directory Patterns

### Product Documentation

**Location**: `docs/`  
**Purpose**: 保存产品愿景、MVP 边界、业务规则和需要长期引用的说明。  
**Pattern**: 当产品边界或业务原则发生变化时，先更新 `docs/`，再同步规格和 steering。

### Specification Documents

**Location**: `.kiro/specs/<feature>/`  
**Purpose**: 每个功能域独立维护需求、设计、任务和研究记录。  
**Pattern**: 按依赖顺序拆分规格，避免一个 spec 同时承载数据模型、AI 编排、检索、反馈和页面交互的全部职责。

已采用的规格边界包括：

- `a3-case-management`：A3 案例数据模型、基础校验和案例 CRUD。
- `llm-case-enrichment`：摘要、结构化提取、标签建议和推荐文案。
- `case-vector-indexing`：embedding 生成、向量入库和 pgvector 索引。
- `cbr-retrieval-recommendation`：结构化过滤、向量召回、相似度重排和推荐解释。
- `recommendation-feedback`：推荐反馈、采纳状态和查询命中关系。
- `mvp-admin-frontend`：基础后台页面和反馈控件。

### Steering Memory

**Location**: `.kiro/steering/`  
**Purpose**: 保存稳定的项目记忆，帮助后续实现保持一致。  
**Pattern**: 记录原则、边界和决策依据，不复制规格细节；当新代码只是遵循既有模式时，不需要更新 steering。

### Planned Application Areas

**Location**: `backend/`, `frontend/`  
**Purpose**: 后续承载 FastAPI 后端和 Vue 3 前端。  
**Pattern**: 后端应按领域能力分层组织；前端应围绕 MVP 后台页面的业务流程组织。具体目录结构以脚手架落地后的本地约定为准。

## Naming Conventions

- **Specs**：使用 kebab-case 功能名，例如 `case-vector-indexing`。
- **Steering files**：使用主题名，例如 `product.md`、`tech.md`、`structure.md`。
- **Documentation**：面向产品和交付边界的文档放在 `docs/`，文件名使用清晰的英文短语。
- **Future code**：后端、前端命名规则应优先遵循各自生态常规，并在脚手架落地后补充到 steering。

## Documentation Consistency Rules

- `docs/product-overview.md` 是产品层单一权威入口（Canonical），用于定义长期愿景、核心场景、能力边界和关键原则。
- `docs/mvp-product.md` 是阶段性落地子集（Derived），仅用于 MVP 交付范围、非目标与技术收敛说明，不单独定义长期愿景。
- 规格文档默认只把 `docs/product-overview.md` 作为上游入口；只有在需要说明 MVP 边界裁剪时，才补充引用 `docs/mvp-product.md`。
- 当两份文档出现冲突时，以 `docs/product-overview.md` 为准；随后应同步修正文档与相关 specs，避免长期漂移。
- 新增产品说明文档必须先声明职责（Canonical 或 Derived），再纳入 specs 引用策略。

## Dependency and Boundary Rules

- 案例管理是基础能力，LLM 增强、向量索引、检索推荐、反馈和前端均依赖它。
- LLM 增强与向量索引可以协作，但不能让 LLM 输出绕过结构化校验直接入库。
- 案例检索推荐依赖案例、LLM 增强和向量索引，但核心数据模型不能反向依赖特定的检索编排框架。
- 反馈闭环依赖推荐结果和查询命中关系，但不应阻塞案例入库与基础检索。
- 前端后台消费后端能力，不在页面层重新实现检索、重排或推荐解释逻辑。

## Code Organization Principles

- 以领域边界组织代码和规格，优先保持共享契约清晰。
- 对跨模块共享的数据结构保持谨慎，特别是案例字段、状态流转、过滤条件、推荐解释和反馈记录。
- 文档和规格中的边界先于实现便利性；如实现需要偏离设计，应记录偏离原因并更新对应文档。
- MVP 阶段优先完成可验证闭环，避免提前引入复杂权限、规则引擎、Agent 编排或训练平台结构。

---
_本文件描述组织模式，不维护完整目录树。脚手架落地后只补充稳定约定。_
