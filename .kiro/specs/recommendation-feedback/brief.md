# Brief: recommendation-feedback

## Problem

MVP 需要验证相似案例推荐是否真的有用。若不记录用户对推荐结果的反馈，团队就无法判断召回质量、推荐解释质量和后续优化方向。

## Current State

`docs/product-overview.md` 是产品权威入口；`docs/mvp-product.md` 在 MVP 阶段要求支持有用/无用、简单评分、是否采纳，并记录查询文本、命中案例和反馈结果。当前还没有反馈数据模型、推荐结果关联方式和后台查看边界。

## Desired Outcome

用户查看推荐结果后，可以记录有用/无用、评分和是否采纳。系统保存查询文本、过滤条件、命中案例、推荐结果标识和反馈内容，为后续召回权重优化和排序策略改进提供数据基础。

## Approach

反馈作为推荐链路后的独立闭环规格，依赖检索推荐结果，但不影响 MVP 的同步召回流程。MVP 只做基础记录和查询，不做自动学习排序，也不引入复杂实验平台。

## Scope

- **In**: 推荐反馈实体、有用/无用、简单评分、采纳标记、查询文本记录、命中案例关联、反馈提交 API、基础反馈查询。
- **Out**: 自动调权、A/B 实验、复杂用户画像、质量评分体系、行业库入选审核。

## Boundary Candidates

- 反馈记录关联一次检索请求和具体推荐结果。
- 反馈不直接修改案例内容或向量索引。
- 反馈数据为后续优化预留，但 MVP 不实现自动排序学习。

## Out of Boundary

- 将反馈自动写回案例质量评分。
- 基于反馈自动选择行业库入库。
- 多维运营分析看板。

## Upstream / Downstream

- **Upstream**: `cbr-retrieval-recommendation`。
- **Downstream**: `mvp-admin-frontend` 提供反馈控件；未来检索优化和质量分析规格可消费反馈数据。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 与 `cbr-retrieval-recommendation` 共享推荐请求和推荐结果标识；与前端后台共享反馈提交交互。

## Constraints

反馈模型要保留原始查询、命中案例和用户判断，避免后续分析只能看到聚合结果。反馈链路失败时，MVP 不应阻塞用户查看推荐结果。
