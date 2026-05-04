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

持久层外键列名为 `store_info_id`；**对外 JSON 统一使用 `store_id`**，取值等于 `store_infos.store_id`，便于与创建/更新请求及前端契约一致。


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

## 6. 规格交叉引用


| 文档                                          | 用途                                                 |
| ------------------------------------------- | -------------------------------------------------- |
| `.kiro/specs/a3-case-management/design.md`  | 案例域 API、`CaseService`、`CaseDetailResponse` 总体设计    |
| `.kiro/specs/llm-case-enrichment/design.md` | `CaseSnapshotProvider`、`CaseInputSnapshot` 入口与映射逻辑 |


**维护约定**：当上游详情 schema 与本文冲突时，以 intentional 变更为准：**先更新本文**，再改实现，并通知下游回归测试。