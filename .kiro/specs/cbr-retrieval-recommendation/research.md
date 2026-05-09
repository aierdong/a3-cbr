# Research & Design Decisions

## Summary

- **Feature**: `cbr-retrieval-recommendation`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - 上游规格已将案例基础字段、LLM 推荐文案与候选向量搜索原语拆分；本规格只负责编排检索与推荐，不反向承担上游数据生命周期。
  - 推荐目标为 Hybrid CBR：硬过滤剔除明显无关案例，问题语义向量做初筛，reranker 产出纯语义相似度，结构化派生字段与业务参数提供可解释的局部评分，再由自实现的 `ScoreAggregator` 聚合得到最终排序。
  - `ScoreAggregator` 作为候选集内的加权聚合组件，逻辑简单、完全可控、易于测试，无外部 CBR 框架依赖。
  - 远程重排默认 model 为 `qwen3-reranker-8b`，应通过独立的 `api_key/model/base_url` 配置与适配层记录分值、状态、耗时及降级原因。

## Research Log

### 上游规格契约

- **Context**: 本规格依赖 `a3-case-management`、`llm-case-enrichment`、`case-vector-indexing`。
- **Sources Consulted**: `.kiro/specs/a3-case-management/requirements.md`、`.kiro/specs/a3-case-management/design.md`、`.kiro/specs/llm-case-enrichment/requirements.md`、`.kiro/specs/llm-case-enrichment/design.md`、`.kiro/specs/case-vector-indexing/requirements.md`、`.kiro/specs/case-vector-indexing/design.md`。
- **Findings**:
  - 案例基础数据由 `A3Case` 与案例管理 API 提供；推荐侧不得写回案例基础字段。
  - LLM 侧的 `RecommendationCopyService` 仅解释已排序候选，不参与重排。
  - 向量索引的 `/api/vector-search` 只返回候选原语、相似度、索引版本与过滤元数据，不承担推荐排序；本规格不直接生成 embedding，也不直接查询 pgvector。
- **Implications**:
  - 本规格需新增 retrieval 模块，消费上游公开契约。
  - 推荐运行记录保存查询哈希、候选引用、分值与状态，不保存反馈结果。
  - 最终响应须同时包含向量分值、语义相似度分、结构化局部相似度、业务参数分、最终聚合分、解释状态与可追溯引用。

### 分值聚合方案选型（已更新：2026-05-02）

- **Context**: Roadmap 要求聚合方案可替换，且核心持久化勿与外部框架强绑定。需验证 CBRKit aggregator 能否满足本规格的加权聚合需求。
- **Sources Consulted**:
  - CBRKit 官方文档：https://wi2trier.github.io/cbrkit/cbrkit.html
  - CBRKit aggregator 模块：https://wi2trier.github.io/cbrkit/cbrkit/sim/aggregator.html
  - PoC 验证代码：`poc/cbrkit_validation/`
- **Findings**:
  - CBRKit 为 Python CBR 工具包，采用函数式 API，覆盖完整 CBR 循环（Retrieve-Reuse-Revise-Retain）。
  - **CBRKit aggregator 核心能力**：
    - ✅ 支持加权聚合（映射格式 + `pooling_weights`）
    - ✅ 不需要完整 casebase（仅处理预计算分值）
    - ❌ **缺失处理不匹配**：以 `default_pooling_weight` 填充缺失项，不会重新归一化权重
    - ❌ **归一化职责缺失**：只负责池化（pooling），不负责 min-max 归一化
    - ❌ **批量处理不匹配**：按单候选处理，无法取得候选集的 min/max
  - **本规格需求**：
    - 候选集内 min-max 归一化（须已知全体候选的 min/max）
    - 缺失分项重加权：`w'_k = w_k / sum(w_j, j in A)`（权重归一化后和为 1.0）
    - 加权求和聚合
  - **适配性结论**：CBRKit aggregator 无法满足本规格，主要原因如下：
    1. 缺失处理逻辑不匹配（`default_pooling_weight` 与重加权需求不一致）
    2. 归一化须自行实现（约 50 行）
    3. 重加权须自行实现（约 30 行）
    4. CBRKit 侧仅剩加权求和（约 1 行）
    5. 为约 1 行代码引入整套框架，收益不足
- **Implications**:
  - **决策**：采用自实现 `ScoreAggregator` 组件
  - **理由**：
    - 逻辑简单、完全可控、易于测试
    - 代码量约 200 行（含类型注解与文档）
    - 无外部依赖与学习成本
    - 已有完整实现与测试，可直接复用
  - **实施**：
    - 实现：`poc/cbrkit_validation/score_aggregator_implementation.py`
    - 测试：`poc/cbrkit_validation/test_score_aggregator.py`
    - 详细分析见本文件末尾「附录：CBRKit vs 自实现对比分析」
  - 设计以 `ScoreAggregator` 替代原计划的外部 CBR 框架；领域层使用系统自定义 `RetrievalCandidate`、`RerankedCandidate`、`RecommendationItem`。
  - `ScoreAggregator` 仅处理向量搜索已返回的候选集，不从全量 SQL casebase 重新检索。
  - 聚合失败时可降级为向量顺序候选，不影响向量搜索契约与响应结构。

### Qwen3-Reranker-8B 重排接入

- **Context**: 本规格需以默认 model `qwen3-reranker-8b` 重排候选，并支持独立 api_key/base_url。
- **Sources Consulted**: Qwen/Qwen3-Reranker-8B 模型卡；vLLM/DeepInfra/Fireworks 等相关 API 说明的检索结果。
- **Findings**:
  - Qwen3-Reranker-8B 为 instruction-aware cross-encoder reranker，常见用法为输入 query 与 documents，输出相关性分值。
  - 部署方可能提供 `/v1/rerank` 或 `/score` 等接口，响应字段随供应商而异。
  - 模型适于基于查询与候选文档做精排；须限制候选数量与输入长度以控制延迟。
- **Implications**:
  - 设计通过 `RerankerClient` 抹平供应商差异；默认模型 id 固定为 `qwen3-reranker-8b`。
  - 响应保存 `semantic_similarity_score`、模型 id、调用状态与耗时；最终排序由 `ScoreAggregator` 聚合结果决定。
  - 重排失败时返回降级状态，按向量候选原始顺序组装结果。

### 产品与 MVP 边界

- **Context**: `docs/product-overview.md` 为产品权威入口，覆盖长期自动推送与行业库愿景；`docs/mvp-product.md` 仅收窄 MVP 范围。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`。
- **Findings**:
  - MVP 侧重手动输入问题、Top-K 相似案例、推荐理由、相似度分值与基础过滤。
  - 自动推送渠道、经营指标触发、巡检触发、行业库高权重候选搜索不在当前规格内。
  - LLM 可辅助推荐解释，不承担主检索职责。
- **Implications**:
  - 本规格只提供手动检索入口的后端契约，不实现 App 消息、邮件或前端页面。
  - 过滤字段与向量索引字段对齐；MVP 仅使用品牌、门店、问题类型、标签、状态、时间范围等上游已支持字段。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 外部 CBR 框架直连持久化 | 由外部框架内部对象直接读全量库并保存推荐运行 | 接入快 | 数据模型与框架强绑定，替换成本高；且会绕过向量索引边界 | Rejected |
| 系统契约 + 自实现聚合器 | 系统定义查询、候选、排序与响应契约；`ScoreAggregator` 做加权聚合 | 可替换、可测试、边界清晰、无外部依赖 | 需自行实现归一化与重加权逻辑（约 200 行） | Selected |
| 纯自研排序流水线 | 不接入任何 CBR 框架，仅手写向量候选重排 | 依赖少 | 与 Selected 方案实质相同，已采纳 | Selected（实质）|

## Design Decisions

### Decision: 自实现 ScoreAggregator（已更新：2026-05-02）

- **Context**: 须对候选集做归一化、缺失分项重加权与加权聚合。经 PoC 验证，CBRKit aggregator 的缺失处理与本规格需求不一致。
- **Alternatives Considered**:
  1. 使用 CBRKit aggregator（归一化与重加权仍须自研，CBRKit 仅做加权求和）
  2. 自实现 ScoreAggregator（含归一化、重加权与聚合）
  3. 混合方案（归一化与重加权自研，加权求和交给 CBRKit）
- **Selected Approach**: 自实现 `ScoreAggregator`，包含：
  1. 候选集内 min-max 归一化
  2. 缺失分项重加权（`w'_k = w_k / sum(w_j, j in A)`）
  3. 加权求和聚合
  4. 并列打破（semantic > business > vector > updated_at > case_id）
- **Rationale**:
  - **CBRKit aggregator 不适用**：
    - 缺失处理为 `default_pooling_weight`，非重加权
    - 不负责归一化（须自研约 50 行）
    - 不负责重加权（须自研约 30 行）
    - 仅剩加权求和（约 1 行）
    - 为约 1 行引入框架，收益不足
  - **自实现优势**：
    - 逻辑完全可控，便于测试与排错
    - 代码约 200 行，结构清晰
    - 无外部依赖与学习成本
    - 已有完整实现与测试，可直接复用
- **Trade-offs**: 需自行维护约 200 行代码，换取完全可控与零依赖。
- **Follow-up**: 编码阶段直接复用 `poc/cbrkit_validation/score_aggregator_implementation.py` 与对应测试。
- **详细分析**: 见本文件末尾「附录：CBRKit vs 自实现对比分析」。

### Decision: 使用 Hybrid CBR 分值拆分与聚合（已更新：2026-05-02）

- **Context**: 用户查询表示当前问题；单靠向量分不足以表达业务适配度。品牌、问题类型等字段宜作硬过滤或业务权重，不宜混入 embedding。
- **Alternatives Considered**:
  1. 仅按向量相似度排序。
  2. 由 reranker 直接决定最终排序。
  3. 拆分语义相似度、结构化局部相似度与业务参数分，再由自研 ScoreAggregator 聚合。
- **Selected Approach**: 向量搜索承担问题语义初筛；reranker 产出纯语义相似度；`structured_suggestions` 产出局部相似度；品牌、业态、门店等级、时间等产出业务参数分；自研 ScoreAggregator 按默认权重与受控请求权重聚合最终分。
- **Rationale**: 分值来源清晰，便于解释与调参；主召回保持问题相似，业务适配通过显式权重影响最终排序；自研 ScoreAggregator 保证缺失分项重加权正确。
- **Trade-offs**: 评分元数据与测试更多；MVP 可先将结构化局部相似度标为 skipped，契约保留。
- **Follow-up**: 实施阶段先锁定默认权重与业务因子范围，避免用户传入无界权重导致排序失控。

### Decision: 推荐运行记录只保存可审计元数据

- **Context**: 下游反馈需关联推荐运行；本规格不负责反馈持久化。
- **Alternatives Considered**:
  1. 保存完整查询、候选正文与解释文本。
  2. 保存查询哈希、候选引用、分值、状态与必要摘要。
- **Selected Approach**: `RecommendationRun` 保存运行标识、查询哈希、过滤条件、候选数量、模型 id、降级状态；`RecommendationItemSnapshot` 保存候选引用与分值。
- **Rationale**: 支撑审计与反馈关联，同时降低敏感文本与供应商输出的留存风险。
- **Trade-offs**: 深度排查可能仍需结合请求日志与上游案例详情。
- **Follow-up**: 与反馈规格对齐 `run_id`、`recommendation_item_id` 引用。

### Decision: 重排失败降级到向量顺序

- **Context**: MVP 需提供可用的相似案例推荐；远程 reranker 可能超时或失败。
- **Alternatives Considered**:
  1. 重排失败则整次请求失败。
  2. 重排失败则返回向量候选并标记降级。
- **Selected Approach**: 返回向量候选原始顺序或可用业务分降级顺序，保留向量相似度；语义相似度或聚合分缺省，并标记 `degraded_reason`。
- **Rationale**: 向量候选仍为有效来源，用户可继续查看结果；响应明确暴露降级状态。
- **Trade-offs**: 降级结果质量可能低于完整重排。
- **Follow-up**: 测试降级响应不包含伪造的语义分或聚合分。

## Risks & Mitigations

- CBRKit API 与实施期版本差异大 — 经适配器封装，并以 fake orchestrator 覆盖核心测试。
- Reranker 延迟拖累检索响应 — 限制候选数量、配置超时；失败时降级为向量顺序。
- 上游过滤字段扩展可能倒逼推荐契约膨胀 — MVP 先保持过滤字段与案例管理、向量索引一致；新增字段须另行复核。
- 推荐解释易被误认为排序依据 — 响应中区分排序分值与自然语言解释状态。

## References

- `docs/product-overview.md` — 长期产品流程与 CBR 目标。
- `docs/mvp-product.md` — MVP 范围、技术栈与检索流程（补充）。
- `.kiro/steering/roadmap.md` — 规格依赖顺序与技术约束。
- `.kiro/specs/a3-case-management/design.md` — 案例基础契约。
- `.kiro/specs/llm-case-enrichment/design.md` — 推荐文案生成边界。
- `.kiro/specs/case-vector-indexing/design.md` — 向量搜索原语与候选响应。
- CBRKit 官方文档：https://wi2trier.github.io/cbrkit/cbrkit.html
- CBRKit aggregator 模块：https://wi2trier.github.io/cbrkit/cbrkit/sim/aggregator.html

---

## 附录：CBRKit vs 自实现对比分析

### 一、需求对比矩阵

| 需求项 | 本规格要求 | CBRKit aggregator 能力 | 匹配度 |
|--------|-----------|----------------------|--------|
| **加权聚合** | 支持命名维度的加权求和 | ✅ 支持映射格式 + 权重 | ✅ 匹配 |
| **缺失分项处理** | 有效分项重加权：`w'_k = w_k / sum(w_j, j in A)` | ❌ 使用 `default_pooling_weight`，不重新归一化 | ❌ **不匹配** |
| **归一化** | 候选集内 min-max 归一化 | ❌ 不负责归一化 | ❌ **不匹配** |
| **批量处理** | 对候选集归一化（需要 min/max） | ❌ 单候选处理 | ❌ **不匹配** |
| **不需要 casebase** | 只处理候选集 | ✅ 只处理分值 | ✅ 匹配 |

### 二、关键差异详解

#### 差异 1：缺失分项处理逻辑

**本规格需求**：
```python
# 原始权重
weights = {'vector': 0.3, 'semantic': 0.4, 'structured': 0.1, 'business': 0.2}

# 候选只有 vector 和 business 可用
available = {'vector': 0.95, 'business': 0.82}

# 有效分项重加权
w'_vector = 0.3 / (0.3 + 0.2) = 0.6
w'_business = 0.2 / (0.3 + 0.2) = 0.4

# 加权求和
final_score = 0.6 * norm(0.95) + 0.4 * norm(0.82)
```

**CBRKit aggregator 逻辑**：
```python
agg = aggregator("mean",
                 pooling_weights={'vector': 0.3, 'semantic': 0.4,
                                  'structured': 0.1, 'business': 0.2},
                 default_pooling_weight=1.0)

result = agg({'vector': 0.95, 'business': 0.82})
# semantic 和 structured 缺失，使用 default_pooling_weight=1.0
# 权重不会重新归一化
```

**结论**：CBRKit 对缺失项采取「填充默认权重」，而非「对有效分项重新归一化权重」。

#### 差异 2：归一化职责

**本规格需求**：
```python
# 步骤 1：对候选集做 min-max 归一化
candidates = [
    {'vector': 0.95, 'semantic': 0.88},
    {'vector': 0.87, 'semantic': 0.92},
    {'vector': 0.82, 'semantic': 0.85},
]

# 归一化 vector 维度
min_vector = 0.82
max_vector = 0.95
norm_vector_1 = (0.95 - 0.82) / (0.95 - 0.82) = 1.0
norm_vector_2 = (0.87 - 0.82) / (0.95 - 0.82) = 0.38
norm_vector_3 = (0.82 - 0.82) / (0.95 - 0.82) = 0.0

# 步骤 2：加权聚合
final_score_1 = 0.3 * 1.0 + 0.4 * norm_semantic_1 + ...
```

**CBRKit aggregator**：
- 只负责池化（pooling），不负责归一化
- 每次处理一个候选，拿不到候选集的 min/max

**结论**：归一化须自行实现。

### 三、方案对比

| 维度 | 方案 A（CBRKit） | 方案 B（自实现）★ |
|------|----------------|----------------|
| **代码量** | ~90 行 | ~200 行 |
| **逻辑正确性** | ⚠️ 须手写重加权 | ✅ 完全正确 |
| **可控性** | ❌ 部分依赖框架 | ✅ 完全可控 |
| **可测试性** | ⚠️ 须 mock CBRKit | ✅ 易于测试 |
| **维护成本** | ⚠️ 依赖框架更新 | ✅ 自主维护 |
| **学习成本** | ❌ 须学习 CBRKit | ✅ 无学习成本 |
| **依赖** | ❌ 增加依赖 | ✅ 无依赖 |

**综合评分**：
- 方案 A：5/10（逻辑不完整，收益小）
- **方案 B：9/10（推荐）**

### 四、实施代码

**完整实现**：`poc/cbrkit_validation/score_aggregator_implementation.py`（约 250 行）

**核心方法**：
```python
class ScoreAggregator:
    def aggregate(self, candidates, weights):
        # 1. 归一化
        normalized = self._normalize_scores(candidates)

        # 2. 对每个候选计算有效权重和最终分值
        for candidate, norm_scores in zip(candidates, normalized):
            effective_weights = self._compute_effective_weights(
                norm_scores, weights
            )
            final_score = sum(
                effective_weights[k] * norm_scores[k]
                for k in norm_scores.keys()
            )

        # 3. 排序（包含并列打破）
        return self._sort_with_tiebreak(aggregated, candidates)
```

**完整测试**：`poc/cbrkit_validation/test_score_aggregator.py`（约 400 行）

**测试覆盖**：
- ✅ 基本聚合（各项分值齐全）
- ✅ 多候选归一化
- ✅ 缺失分项重加权
- ✅ 并列打破（semantic > business > vector > updated_at > case_id）
- ✅ 自定义权重
- ✅ 边界（空候选、全部分项缺失）
- ✅ 真实场景（多候选 + 部分缺失）

**验证结果**：
```bash
$ python3 score_aggregator_implementation.py

聚合结果：
================================================================================

排名 1: case_2
  最终分值: 0.5726
  分值来源: aggregated
  原始分值: {'vector': 0.87, 'semantic': 0.92, 'structured': None, 'business': 0.79}
  归一化分值: {'vector': 0.38, 'semantic': 1.0, 'business': 0.0}
  有效权重: {'vector': 0.33, 'semantic': 0.44, 'business': 0.22}

排名 2: case_3
  最终分值: 0.5000
  ...
```

### 五、编码阶段使用

```bash
# 1. 复制实现代码
cp poc/cbrkit_validation/score_aggregator_implementation.py \
   backend/app/retrieval/score_aggregator.py

# 2. 复制测试代码
cp poc/cbrkit_validation/test_score_aggregator.py \
   backend/tests/retrieval/test_score_aggregator.py

# 3. 调整导入路径和命名空间
# 4. 集成到 RecommendationService
```

### 六、结论

**自实现 ScoreAggregator 为最优方案**：

1. ✅ **逻辑正确**：满足本规格对缺失分项重加权的要求
2. ✅ **代码可控**：约 200 行，结构清晰，便于测试与维护
3. ✅ **无外部依赖**：避免 CBRKit 的学习成本与版本绑定
4. ✅ **已验证**：具备完整实现与测试，可直接复用

**CBRKit aggregator 不适合本规格**，主要原因：
1. ❌ 缺失处理逻辑不匹配（`default_pooling_weight` 与重加权）
2. ❌ 不承担归一化（须自研）
3. ❌ 收益不足（实质仅剩一行加权求和）

---

**附录更新日期**：2026-05-02  
**验证状态**：✅ 已通过 PoC 验证  
**实施就绪度**：✅ 可直接进入编码阶段
