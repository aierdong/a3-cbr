# Requirements Document

## Introduction

`recommendation-feedback` 为门店、督导和后台使用者提供推荐结果反馈记录能力。用户查看 `cbr-retrieval-recommendation` 返回的相似案例后，可以对一次推荐运行或某条推荐项标记**有用性**并可选填写**反馈备注**；系统需要保存查询哈希、可选脱敏查询摘要、过滤条件、命中案例、推荐运行标识、推荐项标识和上述反馈内容。

本规格依赖 `cbr-retrieval-recommendation` 返回的 `recommendation_run_id`、`recommendation_item_id`、推荐项排序、分值、案例引用和查询元数据。它不负责相似案例检索、排序、推荐解释生成、前端控件展示或基于反馈自动学习排序。

## Boundary Context

- **In scope**: 推荐反馈实体、有用/无用、反馈备注（可选）、查询哈希、可选脱敏或截断查询摘要快照、过滤条件快照、命中案例关联、推荐运行和推荐项关联、反馈提交 API、反馈查询 API、基础统计查询、隐私与失败边界。
- **Out of scope**: 推荐召回、向量检索、重排、推荐解释生成、自动调权、A/B 实验、复杂运营分析看板、前端 UI、复杂权限体系、行业库入选审核、案例质量评分自动回写。
- **Adjacent expectations**: 上游推荐规格必须提供稳定的推荐运行标识和推荐项标识；前端后台只消费本规格的提交和查询能力；后续检索优化规格可以读取反馈数据，但不得要求本规格主动改变当前推荐排序。

## Requirements

### Requirement 1: 反馈提交与目标关联

**Objective:** As a 门店用户或督导, I want 对一次推荐运行或具体推荐项提交反馈, so that 团队可以知道推荐结果是否真正有用。

#### Acceptance Criteria

1.1 When 用户提交推荐反馈, the 推荐反馈服务 shall 接收 `recommendation_run_id`、可选 `recommendation_item_id`、有用性及可选反馈备注。
1.2 When 反馈关联具体推荐项, the 推荐反馈服务 shall 校验推荐项属于同一个推荐运行，并保存对应命中案例标识和排序位置。
1.3 When 反馈仅评价整次推荐运行, the 推荐反馈服务 shall 允许 `recommendation_item_id` 为空，并将反馈标记为运行级反馈。
1.4 If 推荐运行标识或推荐项标识不存在、已失效或不匹配, then the 推荐反馈服务 shall 拒绝提交并返回可定位的错误信息。
1.5 The 推荐反馈服务 shall 不触发新的推荐检索、重排、解释生成或案例内容更新。

### Requirement 2: 反馈内容与状态约束

**Objective:** As a 平台运营者, I want 用户侧反馈字段极简且一致, so that 一线愿意提交且 MVP 能快速验证推荐是否有用。

#### Acceptance Criteria

2.1 The 推荐反馈服务 shall 支持有用性结果：`useful`、`not_useful`、`unknown`。
2.2 The 推荐反馈服务 shall 支持可选反馈备注；允许用户只提交有用性而不填写备注。
2.3 If 枚举值非法或反馈备注超过长度限制, then the 推荐反馈服务 shall 返回字段级校验错误，不保存无效反馈。
2.4 When 同一用户对同一反馈目标重复提交反馈, the 推荐反馈服务 shall 按幂等键或唯一约束更新最新反馈，而不是生成无法区分的重复记录。

### Requirement 3: 查询上下文与推荐快照保留

**Objective:** As a 推荐质量分析者, I want 反馈记录保留原始查询和推荐命中上下文, so that 后续能分析召回质量和解释质量。

#### Acceptance Criteria

3.1 When 反馈被保存, the 推荐反馈服务 shall 保留推荐运行的查询哈希、应用过滤条件、候选数量和返回数量；若上游提供已脱敏或截断的查询摘要，则可选复制 `query_summary_snapshot`。
3.2 When 反馈关联推荐项, the 推荐反馈服务 shall 保留案例标识、推荐项标识、排序位置、向量相似度、语义相似度、结构化局部相似度、业务参数分、最终聚合分和解释状态快照。
3.3 The 推荐反馈服务 shall 保留反馈创建人标识、创建时间、更新时间和反馈来源渠道。
3.4 The 推荐反馈服务 shall 不把反馈结果写回案例基础字段、向量索引、推荐运行记录或推荐项快照。
3.5 If 上游推荐运行记录缺少可复制的查询哈希或命中快照, then the 推荐反馈服务 shall 拒绝保存不完整反馈，并返回上游契约不满足的错误信息；不得要求上游提供完整查询原文。

### Requirement 4: 反馈查询与基础统计

**Objective:** As a 平台管理员或推荐质量分析者, I want 查询反馈明细和基础聚合结果, so that 可以判断推荐是否有用并定位问题样本。

#### Acceptance Criteria

4.1 When 管理员查询反馈明细, the 推荐反馈服务 shall 支持按推荐运行、推荐项、案例、用户、时间范围和有用性过滤。
4.2 When 查询单条推荐运行的反馈, the 推荐反馈服务 shall 返回运行级反馈和该运行下各推荐项反馈。
4.3 When 查询基础统计, the 推荐反馈服务 shall 返回反馈数量、有用率（及可按口径拆分的无用占比、`unknown` 占比）和按案例或推荐运行聚合的结果。
4.4 If 查询条件无匹配反馈, then the 推荐反馈服务 shall 返回空列表或零值统计，而不是返回错误。
4.5 The 推荐反馈服务 shall 在查询响应中返回足够的推荐引用字段，便于管理员回溯对应查询和命中案例。

### Requirement 5: 可靠性、隐私与边界失败

**Objective:** As a 用户和系统运营者, I want 反馈链路可靠且不阻塞推荐查看, so that MVP 可以稳定收集质量信号。

#### Acceptance Criteria

5.1 If 反馈提交失败, then the 推荐反馈服务 shall 返回稳定错误状态，并避免影响用户已获得的推荐结果。
5.2 The 推荐反馈服务 shall 在日志、错误响应和基础统计中避免暴露完整查询文本、完整案例正文、向量数组或敏感门店信息。
5.3 The 推荐反馈服务 shall 对反馈备注执行长度限制和基础内容校验，避免保存明显不可用或过长内容。
5.4 While 推荐反馈服务处理并发提交, the 推荐反馈服务 shall 保持同一幂等键或同一用户推荐项反馈的最终记录一致。
5.5 The 推荐反馈服务 shall 为后续检索优化提供可读的反馈数据出口，但不在本规格内实现自动学习排序或实验平台。
