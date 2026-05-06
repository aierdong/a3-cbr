# mvp-admin-frontend 设计修订记录

**修订日期**: 2026-05-06  
**修订原因**: 设计审查发现 3 个关键问题，需修订后重新审查  
**审查决策**: NO-GO → 修订完成，待重新审查

---

## 修订问题总结

### 问题 1: 反馈契约字段不匹配

**问题描述**: Requirements 和 Components 提到 `rating`（1-5 评分）和 `adoption_status`（采纳状态）字段，但后端契约 `recommendation-feedback.openapi.yaml` 不包含这些字段。

**用户决策**: 选项 A - 从前端设计中移除这些字段，只保留 `usefulness` 和 `comment`（快速收敛 MVP）

**修订内容**:
- ✅ 移除 Revalidation Triggers 中的"评分、采纳状态"描述
- ✅ 更新 Components § FeedbackControls State Management，标注"MVP 反馈字段：只支持有用性和备注"
- ✅ 更新 Data Models § FeedbackCreateRequest，移除 `rating` 和 `adoption_status` 注意事项，补充"MVP 反馈字段边界"说明
- ✅ 更新 Error Categories，移除"无效评分"错误类型
- ✅ 更新 Testing Strategy，明确 `FeedbackControls` 只展示有用性和备注输入

---

### 问题 2: 匿名认证策略与 `actor_id` 必填字段的实施歧义

**问题描述**: 设计声明"全匿名"，但 `actor_id` 为必填字段。Data Models 提到使用占位符，但未在 Components 中明确注入策略。

**用户决策**: 方案 A - 在 `FeedbackApiService` 中统一注入固定占位符 `anonymous_user`（标注 MVP）

**修订内容**:
- ✅ 更新 Components § FeedbackApiService Implementation Notes，补充"MVP 匿名策略：`actor_id` 由 `FeedbackApiService` 统一注入固定占位符 `anonymous_user`"
- ✅ 更新 Data Models § FeedbackCreateRequest，将 `actor_id` 映射规则改为"由 `FeedbackApiService` 统一注入固定占位符 `anonymous_user`（MVP 策略）"
- ✅ 更新 Testing Strategy § Unit Tests，补充"`FeedbackApiService` 统一注入 `actor_id: "anonymous_user"` 和 `source_channel: "admin_web"`"
- ✅ 更新 Testing Strategy § Integration Tests，补充反馈请求中包含匿名字段的验证

---

### 问题 3: 案例列表分页策略与契约不一致

**问题描述**: 设计文档暗示使用 offset/limit 分页，但后端契约使用 Keyset 分页（`cursor_created_at`、`cursor_case_id`、`limit`）。

**用户决策**: 按照后端 Keyset 方式分页，调整前端设计

**修订内容**:
- ✅ 更新 Components § CaseApiService API Contract，标注"Keyset 分页"
- ✅ 更新 Components § CaseApiService Implementation Notes，补充"Keyset 分页策略"说明（维护 cursor、判断 `has_next_page`、UI 使用上一页/下一页）
- ✅ 更新 File Structure Plan，新增 `CasePagination.vue` 组件
- ✅ 更新 Components and Interfaces 表格，新增 `CasePagination` 组件，更新 `CaseApiService` 和 `CaseTable` 描述
- ✅ 更新 Data Models § 案例管理数据模型，补充 `PaginatedCaseListResponse` 字段定义和"Keyset 分页前端适配"说明
- ✅ 更新 Testing Strategy § Unit Tests，补充 `CaseApiService` 和 `CasePagination` 的 Keyset 分页测试
- ✅ 更新 Testing Strategy § Integration Tests，补充 Keyset 分页参数传递和下一页加载测试
- ✅ 更新 Testing Strategy § E2E/UI Tests，补充用户点击"下一页"的测试场景
- ✅ 更新 Performance & Scalability，明确"列表分页使用 Keyset 分页，依赖后端返回的 cursor"

---

## 修订影响范围

### 修改文件
- `.kiro/specs/mvp-admin-frontend/design.md` - 设计文档主体修订
- `.kiro/specs/mvp-admin-frontend/spec.json` - 更新阶段状态为 `design-revised`

### 未修改文件
- `.kiro/specs/mvp-admin-frontend/requirements.md` - Requirements 5.1-5.2 已符合后端契约（只提到有用性和备注），无需修改
- `.kiro/specs/mvp-admin-frontend/tasks.md` - 设计修订后需重新生成任务

---

## 后续步骤

1. ✅ 设计文档修订完成
2. ⏳ 重新运行 `/kiro-validate-design mvp-admin-frontend` 进行二次审查
3. ⏳ 审查通过后，运行 `/kiro-spec-tasks mvp-admin-frontend` 重新生成实施任务
4. ⏳ 任务审查通过后，进入实施阶段

---

## 修订验证清单

- [x] 反馈字段边界明确（只支持 usefulness 和 comment）
- [x] `actor_id` 注入策略明确（`FeedbackApiService` 统一注入 `anonymous_user`）
- [x] Keyset 分页策略完整（cursor 维护、has_next_page 判断、UI 交互模式）
- [x] 新增 `CasePagination` 组件定义
- [x] 测试策略覆盖 Keyset 分页和匿名反馈
- [x] spec.json 状态更新为 `design-revised`

---

**修订完成时间**: 2026-05-06 21:30:00+08:00
