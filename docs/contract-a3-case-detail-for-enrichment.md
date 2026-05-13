# A3 案例详情 → LLM 案例增强：字段语义说明文档

本文档定义 `a3-case-management` 的 `CaseDetailResponse` 与 `llm-case-enrichment` 的 `CaseInputSnapshot` 之间的字段映射关系，作为字段语义说明文档。两个模块在同一代码库内，通过 Pydantic schema 保证类型安全，本文档仅作为字段含义、枚举值的参考说明。

---

## 1. 问题背景

- `llm-case-enrichment` 设计中出现 `CaseSnapshotProvider.load_snapshot(case_id) -> CaseInputSnapshot`，需要明确字段映射关系。
- `a3-case-management` 设计中出现 `CaseService.get_case(...) -> CaseDetailResponse`，需要统一字段命名。
- 本文档作为字段语义说明，供两规格及实现共同参考。

---

## 2. 边界与依赖方向


| 角色      | 规格                    | 职责                                                              |
| ------- | --------------------- | --------------------------------------------------------------- |
| 上游（提供者） | `a3-case-management`  | 定义并实现案例详情：`CaseDetailResponse`                                  |
| 下游（消费者） | `llm-case-enrichment` | `CaseSnapshotProvider` 读取上游详情并映射为 `CaseInputSnapshot`，不修改案例基础数据 |


允许的读取方式（等价契约，二选一或并存）：

1. **进程内**：`CaseService.get_case(case_id: str) -> CaseDetailResponse`（与同后端内模块集成一致）。
2. **HTTP**：`GET /api/a3-cases/{case_id}`，成功时响应体与 `CaseDetailResponse` 的 JSON 形状一致（见第 3 节）。

错误：不存在案例时，上游返回 **404**，稳定错误码 `CASE_NOT_FOUND`（见上游错误信封）；下游加载快照时应视为失败，**不得**调用 LLM。

---

## 3. `CaseDetailResponse`（JSON）字段定义

约定：**HTTP 与进程内 DTO 使用同一套 JSON 属性名（snake_case）**。下列字段为 `llm-case-enrichment` 的 `CaseSnapshotProvider` 必须能够依赖的最小集合；上游可增加字段，但不得在无通知的前提下删除、改名或改变下列字段语义。

### 3.1 标识与时间


| JSON 属性      | 类型               | 必填  | 说明                     |
| ------------ | ---------------- | --- | ---------------------- |
| `case_id`    | string           | 是   | 案例主键                   |
| `status`     | string           | 是   | 见 §4.1 `CaseStatus`     |
| `created_at` | string（ISO 8601） | 是   | 案例创建时间                 |
| `updated_at` | string（ISO 8601） | 是   | 案例最后成功更新时间（用于增量与过期判断） |


### 3.2 A3 核心内容字段


| JSON 属性               | 类型     | 必填  | 说明                                                     |
| --------------------- | ------ | --- | ------------------------------------------------------ |
| `problem_description` | string | 是   | 问题描述                                                   |
| `problem_type`        | string | 是   | 受控问题类型，见 §4.2                                          |
| `context`             | object | 是   | JSON 对象；最小键至少包含 `scene`（string，非空）。允许扩展键               |
| `root_cause`          | string | 是   | 根因                                                     |
| `solution_steps`      | array  | 是   | 元素最小形状：`order`（int，从 1 递增）、`content`（string，非空）。允许扩展字段 |
| `outcome`             | object | 是   | 最小键：`result`（§4.3）、`notes`（string，可为空）。允许扩展键           |


### 3.3 门店镜像（过滤维度）

持久层外键列名为 `store_id`；**对外 JSON 统一使用 `store_id`**，取值等于 `store_infos.store_id`，便于与创建/更新请求及前端契约一致。


| JSON 属性          | 类型     | 必填  | 说明              |
| ---------------- | ------ | --- | --------------- |
| `store_id`       | string | 是   | 关联门店主键          |
| `store_name`     | string | 是   | 门店名称            |
| `brand_id`       | string | 是   | 品牌标识            |
| `brand_name`     | string | 是   | 品牌名称            |
| `business_type`  | string | 是   | 业态（受控枚举由上游维护）   |
| `store_scale`    | string | 是   | 门店规模（受控枚举由上游维护） |
| `franchise_type` | string | 是   | 加盟类型（受控枚举由上游维护） |
| `city`           | string | 是   | 城市              |
| `city_tier`      | string | 是   | 城市层级（受控枚举由上游维护） |


可选：`store_mirror_updated_at`（string ISO 8601），表示门店镜像行的 `updated_at`。若上游暂不返回，下游不得将其作为必填。

### 3.4 明确排除（不应出现在详情中的依赖）

下列内容**不属于**本契约中的 `CaseDetailResponse`，`CaseSnapshotProvider` 也不得依赖其存在：

- 向量、embedding、相似度、推荐分值、推荐理由持久化字段  
- 反馈、采纳状态与内部诊断字段  
- 任意 LLM 派生列（摘要、标签建议等）

---

## 4. `CaseInputSnapshot`（下游视图）

`CaseInputSnapshot` **不是**替代上游 API 的新 REST 资源，而是 `CaseSnapshotProvider` 在内存中的结构化结果，其**上游来源字段**必须与 §3 可一一映射（允许下游增加自有字段，但不得与 §3 语义冲突）。

### 4.1 与 `CaseDetailResponse` 的映射


| `CaseInputSnapshot` 字段来源                                                                                                  | 规则                             |
| ------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `case_id`, `status`, `created_at`, `updated_at`                                                 | 直接取自响应根级同名属性 |
| `problem_description`, `problem_type`, `context`, `root_cause`, `solution_steps`, `outcome`                               | 直接取自响应根级同名属性                   |
| `store_id`, `store_name`, `brand_id`, `brand_name`, `business_type`, `store_scale`, `franchise_type`, `city`, `city_tier` | 直接取自响应根级同名属性（扁平门店画像，与 §3.3 一致） |


### 4.2 下游可扩展字段（不属于上游契约）

下列字段由 `llm-case-enrichment` 自行生成或配置驱动，**不作为** `a3-case-management` 的承诺：

- 为 Prompt 组装的「允许外发文本块」、哈希或裁剪痕迹（只要不回写上游）

---

## 5. 枚举与语义

### 5.1 `CaseStatus`（案例基础状态）

允许取值（精确字符串）：


| 值          | 含义（摘要）                                                        |
| ---------- | ------------------------------------------------------------- |
| `draft`    | 草稿；业务上 `llm-case-enrichment` 默认不得对其执行增强（与上游「未完成下游处理」语义一致） |
| `active`   | 可用，可编辑                                                        |
| `archived` | 归档，只读                                                         |


状态迁移与编辑约束以上游规格为准。

### 5.2 `problem_type` 与业态/规模类枚举

`problem_type`、`business_type`、`store_scale`、`franchise_type`、`city_tier` 均为**受控字符串枚举**，**允许取值集合以上游实现（校验器/配置）为权威**。本契约要求：

- 下游以 **string** 传递与校验，不在此文档硬编码完整列表（避免与上游漂移双维护）。  
- 当上游扩展或重命名枚举值时，须通知下游回归测试。

### 5.3 `outcome.result`（效果结果最小集）

路径：`outcome.result`，允许取值：


| 值           | 含义         |
| ----------- | ---------- |
| `improved`  | 已改善        |
| `no_change` | 无明显改善      |
| `unknown`   | 未评估 / 暂不可得 |


---

## 6. 增强触发条件与「提交且摘要」跨规格编排

本节是 **「提交且摘要」** 的唯一维护正文，涉及 `a3-case-management`、`llm-case-enrichment` 与 `case-vector-indexing`；各 `.kiro/specs/*/design.md` 仅保留指向本文的链接。

### 6.1 触发职责

**触发主体**：前端（`mvp-admin-frontend`）。

**「提交且摘要」调用顺序**（**前一步 HTTP 成功且满足条件后，才执行下一步**）：

1. `POST /api/a3-cases` 或 `PUT /api/a3-cases/{case_id}`：**保存案例**。若失败则停止，不向用户隐藏保存错误。
2. `POST /api/a3-cases/{case_id}/enrichment-runs`：**触发并完成一次增强运行**（当前实现为请求内跑完 LLM 流水线并返回终态，见 §6.4）。若 HTTP 失败或响应体中运行状态非 `succeeded`，则 **不执行第 3 步**。
3. 仅当第 2 步响应中 **`status === succeeded`**（对齐 `EnrichmentRunResponse`）时：`POST /api/a3-cases/{case_id}/vector-index/refresh`，请求体至少 `{ "force_rebuild": false }`，可附带 `requested_by`（如 `submit-with-summary`）便于审计。若本步 HTTP 失败，案例与增强结果仍以服务端状态为准，前端须单独提示向量化失败。

**业务触发条件**：

- **首次创建案例**：用户点击「提交且摘要」，案例保存后执行增强；增强成功后再执行向量刷新。
- **编辑已有案例**：同上；是否在内容未变时仍触发由产品决定（MVP 可依按钮意图一律触发或由前端 diff §6.2 字段后决定）。
- **手动重试**：用户在详情或编辑页对失败步骤重试——增强可再次 `POST .../enrichment-runs`，或若存在 `retryable` 运行则使用 `POST /api/enrichment-runs/{run_id}/retry`（见 `llm-case-enrichment` OpenAPI）；向量可对失败任务 `POST /api/vector-index/jobs/{job_id}/retry` 或直接再次 `POST .../vector-index/refresh`（见 `case-vector-indexing` OpenAPI）。

### 6.2 触发条件：字段变更范围

**触发重新增强的字段**（A3 核心内容字段）：
- `problem_description`（问题描述）
- `context`（场景上下文）
- `root_cause`（根因分析）
- `solution_steps`（解决步骤）
- `outcome`（效果结果）

**不触发重新增强的字段**（门店镜像与元数据字段）：
- `store_id`、`store_name`、`brand_id`、`brand_name`、`business_type`、`store_scale`、`franchise_type`、`city`、`city_tier`
- `status`（案例状态变更，如 `active` → `archived`）
- `created_at`、`updated_at`

**实现说明**：
- MVP 阶段由前端判断是否触发增强（用户点击"提交且摘要"按钮时触发，点击"保存"按钮时不触发）。
- 后续阶段可由后端根据字段变更范围自动判断是否触发（通过事件总线或字段 diff 检测）。

### 6.3 失败处理

- **增强失败不回滚案例更新**：案例已保存且可查看，增强运行记录可为 `failed`、`validation_failed`、`retryable` 等（见 `EnrichmentRunStatus`）。
- **向量刷新失败不回滚案例与增强**：已向量化失败或跳过（增强未 `succeeded`）时，前端应在详情中展示状态并提供重试。
- **用户可手动重试**：见 §6.1「手动重试」。
- **下游消费约定**：向量索引与检索侧只应依赖一致快照；派生结果消费侧只消费 `current_result.status=valid`（详情查询见 §6.5）。

### 6.4 请求内终态语义（与历史「纯异步」文案的纠偏）

当前后端实现中，`POST .../enrichment-runs` 与 `POST .../vector-index/refresh` 均在**单次 HTTP 请求内执行至可返回的终态**（成功或失败），前端在「提交且摘要」流程中**会等待**这两步完成后再跳转或结束 loading。此前若文档写「触发后立即返回、后台异步、无需轮询」，以**本节为准**。

### 6.5 详情态：增强与向量『是否成功』（不写回 `CaseDetailResponse`）

管理后台案例详情需要区分 **增强是否成功**、**向量化是否成功**，**不**扩展 `GET /api/a3-cases/{case_id}` 的合同最小集时，前端在已加载案例本体后**并行**请求：

- `GET /api/a3-cases/{case_id}/enrichment` → `CaseEnrichmentStatusResponse`：`latest_run`、`current_result`。
- `GET /api/a3-cases/{case_id}/vector-index` → `VectorIndexStatusResponse`：`status`、`latest_job`、`last_error_code`、`message`。

**建议展示规则**：

- **增强成功**：`latest_run?.status === succeeded` 且 `current_result?.status === valid`（枚举以 `llm-case-enrichment` OpenAPI 为准）。
- **向量化成功**：聚合 `status` 为 `published` 或 `succeeded`（枚举以 `case-vector-indexing` OpenAPI 为准）；`degraded`、`unsearchable` 等单列说明，避免与「成功检索」混淆。
- 任一侧点不可用时，详情页仍可展示案例基础字段，仅在派生区块提示加载失败并重试加载。

契约细节见 `docs/contracts/llm-case-enrichment.openapi.yaml`、`docs/contracts/case-vector-indexing.openapi.yaml`。

---

## 7. 规格交叉引用


| 文档                                          | 用途                                                 |
| ------------------------------------------- | -------------------------------------------------- |
| `.kiro/specs/a3-case-management/design.md`  | 案例域 API、`CaseService`、`CaseDetailResponse` 总体设计 |
| `.kiro/specs/llm-case-enrichment/design.md` | `CaseSnapshotProvider`、`CaseInputSnapshot`、增强模块边界 |
| `.kiro/specs/case-vector-indexing/design.md` | 向量索引、`VectorIndexService`、刷新与状态语义 |


**维护约定**：当上游详情 schema 与本文冲突时，以 intentional 变更为准：**先更新本文**，再改实现，并通知下游回归测试。