# Deviation Record

## 1. Core Summary
- **Associated Task/Spec**: `llm-case-enrichment` 设计审查修订
- **Deviation Type**: Contract / Architecture

## 2. Deviation Details

### 2.1 事务边界与职责分离

- **Baseline**: 设计文档在多处描述"在同一数据库事务内先将既有 `pending_review` 更新为 `stale`，再写入新的 `pending_review`"，但未明确该事务由哪个组件负责。
- **Current Status**: 
  - 明确 `EnrichmentRepository.complete_run` 在同一事务内完成三个原子操作：作废旧 `pending_review` → 写入新 `pending_review` → 更新运行记录状态。
  - `EnrichmentService` 的后置条件改为引用 Repository 的事务保证，删除重复描述。
- **Root Cause**: 设计初稿时职责边界描述不够精确，导致事务归属模糊。

### 2.2 推荐文案端点的 HTTP 状态码与降级策略

- **Baseline**: 
  - API Contract 表格中推荐文案端点的 Errors 列仅包含 `503`，未提及降级响应的 HTTP 状态码。
  - Error Categories 将 LLM 超时归类为 External Dependency Errors (503)，但实际行为是 HTTP 200 + 降级响应。
- **Current Status**:
  - API Contract 补充推荐文案端点的三种响应场景：成功（HTTP 200 + `status: succeeded`）、降级（HTTP 200 + `status: degraded`）、服务不可用（HTTP 503，仅系统级故障）。
  - Error Categories 新增 "Business Degradation (200)" 类别，将推荐文案的 LLM 失败从 503 移至该类别。
  - Implementation Notes 明确："推荐文案端点的 LLM 失败不返回 503，而是返回 HTTP 200 + 降级响应，仅在无法构造降级响应时（如数据库故障）才返回 503"。
- **Root Cause**: 设计初稿时未充分区分"业务能力降级"与"服务不可用"的语义差异，导致 HTTP 状态码与业务行为不一致。

### 2.3 多模型配置隔离的实现指导

- **Baseline**: 设计文档定义了四个独立配置类，但缺少配置来源、实例化、依赖注入和测试验证点的具体实现指导。
- **Current Status**:
  - 补充配置来源：从 `.env` 文件读取环境变量（如 `ENRICHMENT_LLM_PROVIDER`、`ENRICHMENT_LLM_MODEL_ID` 等）。
  - 补充配置加载：在 `backend/app/core/config.py` 中定义 `load_app_config() -> AppConfig` 函数，应用启动时调用一次并存储为全局单例。
  - 补充依赖注入示例：定义 `get_enrichment_llm_config()` 依赖函数，在 Router 中通过 `Depends()` 注入。
  - 补充配置隔离测试验证点：验证配置对象独立性（内存地址不同）、配置值互不干扰、共享 `LLMClient` 正确路由到对应配置。
- **Root Cause**: 设计初稿聚焦于配置类定义，未充分展开实现细节，导致后续规格复用时可能出现不一致的实现模式。

## 3. Risk Assessment

- **Impact Scope**: 
  - 事务边界修订影响 `EnrichmentRepository` 和 `EnrichmentService` 的实现。
  - HTTP 状态码修订影响下游 `cbr-retrieval-recommendation` 的错误处理逻辑。
  - 配置隔离修订影响 `backend/app/core/config.py` 和所有使用 LLM/Embedding/Reranker 的规格。
- **Risk Level**: Medium
- **Risk Description**: 
  - 若不修订事务边界，实现时可能出现数据不一致或重复 `pending_review` 记录。
  - 若不修订 HTTP 状态码，下游可能误判业务降级为服务不可用，导致错误的重试或告警策略。
  - 若不补充配置隔离实现指导，后续规格可能采用不一致的配置加载方式，增加维护成本。

## 4. Decision & Action

- **Proposed Resolution**: 
  - [x] **Update Source**: 更新 `design.md` 以反映修订后的事务边界、HTTP 状态码和配置隔离实现指导。
  
- **Action Plan**:
  1. ✅ 修订 `EnrichmentRepository` 的 Service Interface，补充 `complete_run` 的事务语义说明（包含伪代码示例）。
  2. ✅ 修订 `EnrichmentService` 的后置条件，删除重复的事务描述，改为引用 Repository 的事务保证。
  3. ✅ 修订 `EnrichmentRouter` 的 API Contract，补充推荐文案端点的三种响应场景说明。
  4. ✅ 修订 `EnrichmentRouter` 的 Implementation Notes，明确推荐文案端点的降级策略。
  5. ✅ 修订 Error Categories，新增 "Business Degradation (200)" 类别。
  6. ✅ 修订多模型配置隔离策略，补充 .env 配置来源、配置加载、依赖注入示例和测试验证点。
  7. ✅ 修订 Integration Tests，补充配置隔离测试的具体验证点。

## 5. Review Outcome

- **Original Assessment**: NO-GO（需解决关键问题后重新审查）
- **Post-Revision Status**: 所有关键问题已按建议修订，设计文档现已满足实现就绪标准。
- **Next Steps**: 
  - 设计文档已更新为新的 Source of Truth。
  - 可进入任务生成阶段：运行 `/kiro-spec-tasks llm-case-enrichment` 生成实现任务。
  - 实现时须严格遵循修订后的事务语义、HTTP 状态码和配置隔离策略。

## 6. Traceability

- **Requirements**: 需求 4.7（待审核结果唯一性保证）、需求 5.5（推荐文案失败降级）、需求 6.5（隐私配置门控）
- **Design Sections**: 
  - §3.1 `EnrichmentRouter` API Contract
  - §3.2.2 `EnrichmentService` 后置条件
  - §3.2.4 `RecommendationCopyService` 失败策略
  - §3.4.1 多模型配置隔离策略
  - §3.5.2 `EnrichmentRepository` Service Interface
  - §6.2 Error Categories
  - §8.2 Integration Tests
- **Evidence**: Git diff 显示 6 处关键修订，涵盖事务边界、HTTP 状态码、配置实例化和测试验证点。
