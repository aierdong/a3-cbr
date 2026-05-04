# 偏差记录：移除 LLM 案例增强中的契约版本管理机制

## 基本信息

- **日期**: 2026-05-03
- **影响规格**: `llm-case-enrichment`
- **影响文档**: 
  - `.kiro/specs/llm-case-enrichment/design.md`
  - `.kiro/specs/llm-case-enrichment/requirements.md`
  - `.kiro/specs/llm-case-enrichment/tasks.md`
  - `.kiro/specs/llm-case-enrichment/research.md`
  - `docs/contract-a3-case-detail-for-enrichment.md`
- **决策人**: 产品/架构团队

## 原始设计

### 设计内容

原设计引入了复杂的契约版本管理机制：

1. **版本字段**：
   - `CaseDetailResponse.case_contract_version`（上游响应字段）
   - `CaseEnrichmentRun.input_contract_version`（运行记录审计字段）
   - `CaseEnrichmentRun.mapping_version`（本地映射版本）
   - 配置项：`case_contract_version`、`mapping_version`

2. **运行时检查**：
   - 惰性探测：首次加载快照时完成版本握手
   - 版本不匹配时 fail-closed，返回 `CASE_INPUT_CONTRACT_MISMATCH`
   - 健康检查端点返回多个版本字段

3. **运维流程**：
   - 版本不匹配时需手动更新配置并重启服务
   - 单版本映射策略，不支持多版本并存

### 设计意图

- 确保上游 `CaseDetailResponse` 与下游 `CaseInputSnapshot` 的字段映射一致性
- 在字段变更时提供运行时保护
- 提供审计追溯能力

## 偏差说明

### 变更内容

**完全移除**契约版本管理机制：

1. **删除版本字段**：
   - 从 `CaseDetailResponse` 删除 `case_contract_version`
   - 从 `CaseEnrichmentRun` 删除 `input_contract_version` 和 `mapping_version`
   - 从配置删除相关配置项

2. **删除运行时检查**：
   - 移除版本握手逻辑
   - 移除 `CASE_INPUT_CONTRACT_MISMATCH` 错误码
   - 简化健康检查端点

3. **简化 `CaseSnapshotProvider`**：
   - 直接进行类型映射，无版本检查
   - 依赖 Pydantic schema 的编译时类型检查

4. **重新定位 contract 文档**：
   - `docs/contract-a3-case-detail-for-enrichment.md` 改为纯字段语义说明文档
   - 删除版本管理相关章节（原 §6）
   - 保留字段定义和枚举说明

### 变更原因

1. **过度设计**：
   - 两个模块在**同一代码库、同一进程、同一部署单元**内
   - 共享 Pydantic schema 定义
   - 不存在"双方订立契约、独立演进、需要协商版本"的场景

2. **类型系统已提供保障**：
   - Pydantic model 变化 → 类型检查失败
   - 字段改名/删除 → 编译时发现
   - 不需要运行时版本检查

3. **增加不必要的复杂度**：
   - 运行时版本检查逻辑
   - 配置文件维护 + 手动重启
   - 健康检查端点复杂度
   - 运维负担

### 何时需要版本管理

版本管理适用于以下场景（本项目不符合）：
- 跨系统边界（不同代码库、独立部署）
- 需要向后兼容的公开 API
- 客户端与服务端独立演进

本项目的实际情况：
- 单体后端（或紧密耦合的模块）
- 同一次部署、同一份代码
- 数据结构变化时，所有模块同步更新

## 影响分析

### 受影响组件

1. **`CaseSnapshotProvider`**：
   - 移除版本握手逻辑
   - 简化为直接类型映射

2. **`EnrichmentRepository`**：
   - 移除运行记录中的版本字段持久化

3. **`EnrichmentRouter`**：
   - 简化健康检查端点响应

4. **配置与错误处理**：
   - 移除版本相关配置项
   - 移除 `CASE_INPUT_CONTRACT_MISMATCH` 错误码

### 需求变更

- **删除 Requirement 1.5**：上游契约变化重新校验
- **删除 Requirement 1.6**：契约版本读取与比对
- **删除 Requirement 1.7**：版本不匹配 fail-closed
- **删除 Requirement 1.8**：持久化版本审计字段

### 任务变更

- **Task 1.1**：移除契约门控配置和错误码
- **Task 1.2**：移除运行记录中的版本字段
- **Task 2.1**：移除版本握手检查
- **Task 2.5**：移除版本字段持久化
- **Task 4.1**：简化健康检查端点
- **Task 5.4**：移除版本不匹配测试

## 实施指导

### 保留的价值

1. **Contract 文档作为字段语义说明**：
   - 枚举值定义
   - 字段业务含义
   - 映射关系说明

2. **`CaseSnapshotProvider` 作为适配器层**：
   - 隔离两个模块的直接依赖
   - 提供清晰的数据转换边界

3. **明确的数据结构定义**：
   - `CaseDetailResponse` → `CaseInputSnapshot` 映射
   - 通过 Pydantic schema 保证类型安全

### 变更通知机制

当上游 `CaseDetailResponse` 字段发生变更时：
1. 更新 `docs/contract-a3-case-detail-for-enrichment.md` 字段说明
2. 更新 Pydantic schema 定义
3. 类型检查失败会在编译/测试阶段发现
4. 通知下游团队进行回归测试

## 批准与追踪

- **批准人**: [待填写]
- **批准日期**: 2026-05-03
- **关联 Issue/PR**: [待填写]
- **后续行动**: 
  - [ ] 更新实现代码（如已开始实现）
  - [ ] 更新集成测试
  - [ ] 通知相关团队成员

## 参考

- 原始设计：`.kiro/specs/llm-case-enrichment/design.md` (commit before 2026-05-03)
- 讨论记录：[本次对话]
