# Brief: mvp-admin-frontend

## Problem

MVP 需要一个可操作的后台入口，来验证案例录入、检索推荐和反馈闭环。若只有后端 API，业务和产品团队很难持续录入案例、观察推荐质量并收集反馈。

## Current State

`docs/product-overview.md` 是产品权威入口；`docs/mvp-product.md` 在当前阶段要求提供基础后台管理页面，前端技术栈为 Vue。当前仓库还没有前端应用、页面路由、表单和 API 对接约定。

## Desired Outcome

提供 Vue 3 基础后台页面，支持创建和编辑 A3 案例、查看案例列表和详情、输入新问题进行相似案例检索、展示推荐理由和相似度分值，并提交基础反馈。

## Approach

前端后台作为 MVP 最后一层规格，消费后端案例、检索推荐和反馈 API。页面优先覆盖验证闭环，不引入复杂设计系统、复杂权限和多端深度适配。

## Scope

- **In**: 案例表单、案例列表、案例详情、检索输入页、Top-K 推荐结果展示、推荐理由和相似度展示、反馈控件、基础错误和加载状态。
- **Out**: App 内消息、邮件推送、复杂数据看板、角色权限管理、品牌多租户管理、移动端深度适配。

## Boundary Candidates

- 前端只消费已定义 API，不拥有业务规则。
- 页面围绕 MVP 验证闭环组织，而不是完整慧运营后台。
- 反馈提交与推荐展示解耦，反馈失败不影响推荐结果可见性。

## Out of Boundary

- 经营指标趋势看板。
- 巡检报告发起入口。
- 行业库审核后台。
- 复杂菜单、组织和权限配置。

## Upstream / Downstream

- **Upstream**: `a3-case-management`、`cbr-retrieval-recommendation`、`recommendation-feedback`，并展示部分 `llm-case-enrichment` 生成内容。
- **Downstream**: MVP 用户验证、产品验收和后续 UI/权限规格。

## Existing Spec Touchpoints

- **Extends**: none
- **Adjacent**: 与所有后端规格共享 API 契约；不应反向驱动后端数据模型膨胀。

## Constraints

前端采用 Vue 3，不使用 Vue 2 或旧 Vue CLI。MVP 页面以清晰可验证为优先，避免过早引入重型组件体系或复杂权限框架。
