# Implementation Plan

- [ ] 1. 建立推荐反馈基础设施

- [x] 1.1 扩展反馈配置与错误码
  - 增加反馈备注最大长度、统计查询默认范围和反馈功能开关配置。
  - 增加反馈目标不存在、目标不匹配和字段校验相关错误码。
  - 仅向共享配置和错误映射追加本规格所需配置值与错误码，不拥有 `backend/app/core/config.py`、`backend/app/core/errors.py` 或 `ErrorMapper` 基础实现。
  - 完成后非法输入和上游契约问题可以返回稳定错误码，日志不包含敏感正文。
  - _Requirements: 1.4, 3.5, 5.1, 5.2, 5.3_

- [x] 1.2 建立推荐反馈存储结构
  - 创建反馈记录的数据结构和迁移，保存反馈目标、提交者、反馈内容和审计字段。
  - 增加同一用户同一反馈目标唯一约束（PostgreSQL 15+ 使用 `UNIQUE NULLS NOT DISTINCT`），以及运行、推荐项、案例、用户、时间和状态查询索引。
  - 运行级反馈的 `recommendation_item_id` 为 NULL，推荐项级反馈为非 NULL 上游标识。
  - 查询上下文（查询哈希、过滤条件等）和推荐项详细信息（分值、排序位置等）通过关联查询 `recommendation_runs` 和 `recommendation_item_snapshots` 获取，不在反馈表中冗余存储。
  - 完成后测试数据库可以应用迁移，并能保存运行级和推荐项级反馈记录。
  - _Requirements: 1.2, 1.3, 2.4, 3.1, 3.2, 3.3, 5.4_

- [x] 1.3 定义反馈请求、删除、查询、统计和响应契约
  - 定义反馈提交、反馈删除、反馈目标、有用性、备注、来源渠道、明细查询和统计查询契约。
  - 响应包含反馈标识、推荐运行标识、推荐项标识（运行级为 None）、案例标识、反馈结果、目标级别和时间字段。
  - 完成后 API、服务、测试和后续前端可以复用同一套稳定 schema。
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 2.4, 4.5, 5.3_

- [ ] 2. 实现反馈目标校验与提交

- [x] 2.1 实现推荐引用解析
  - 根据推荐运行标识和可选推荐项标识读取上游推荐运行与推荐项标识。
  - 校验推荐项属于同一推荐运行，并识别运行不存在、推荐项不存在、目标不匹配。
  - 返回关联数据（如 `case_id`）。
  - 完成后反馈服务可以获得推荐运行和推荐项的存在性与一致性确认，以及案例标识（推荐项级必填，运行级为 None）。
  - _Requirements: 1.2, 1.4, 3.5_
  - _Boundary: RecommendationReferenceResolver_

- [x] 2.2 (P) 实现反馈字段校验和目标类型判断
  - 校验有用性、备注长度和来源渠道。
  - 支持推荐项级反馈和运行级反馈两种目标，`recommendation_item_id` 为 None 时明确标记为运行级反馈。
  - 完成后非法字段在保存前返回字段级错误，合法请求可生成规范化反馈输入。
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 5.3_
  - _Boundary: FeedbackSchemas_

- [x] 2.3 实现反馈保存
  - 根据同一用户同一反馈目标唯一规则执行新增或更新。
  - 保存最新有用性、备注、来源渠道和审计字段。
  - 数据库唯一约束保证并发提交的幂等性。
  - 完成后重复提交不会生成无法区分的重复记录，并发提交最终保持一条最新反馈。
  - _Requirements: 2.4, 3.1, 3.2, 3.3, 5.4_
  - _Boundary: FeedbackRepository_
  - _Depends: 2.1, 2.2_

- [x] 2.4 实现反馈提交服务
  - 串联字段校验、推荐引用解析、目标关系校验和反馈保存。
  - 确认提交路径不调用推荐检索、重排、解释生成或上游写回。
  - 完成后有效请求返回已保存反馈，目标错误或保存失败返回稳定错误且不影响已展示推荐结果。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.4, 5.1_
  - _Boundary: FeedbackService_
  - _Depends: 2.1, 2.2, 2.3_

- [ ] 3. 实现反馈删除与查询

- [x] 3.1 (P) 实现反馈删除
  - 支持按 `feedback_id`、`case_id`、`recommendation_run_id`、`recommendation_item_id` 删除反馈（至少提供一个过滤条件）。
  - 返回稳定删除结果：`success`、`deleted_count`、`deleted_at`；未命中时返回 `deleted_count=0` 且保持幂等成功。
  - 记录删除原因（`reason`）和删除者（`requested_by`），并满足隐私日志约束。
  - 完成后案例删除可触发反馈删除，定时清理程序可删除无效记录。
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - _Boundary: FeedbackRepository, FeedbackService_
  - _Depends: 2.3_

- [x] 3.2 (P) 实现反馈明细过滤查询
  - 支持按推荐运行、推荐项、案例、用户、时间范围和有用性过滤。
  - 查询结果返回反馈结果、推荐引用字段和审计字段，并补充关联上下文字段：`query_hash`、过滤条件摘要、候选数量和返回数量（通过关联查询，不在反馈表冗余）。
  - 推荐项级结果补充关联明细字段：排序位置、向量相似度、语义相似度、结构化局部相似度、业务参数分、最终聚合分和解释状态（通过关联查询，不在反馈表冗余）。
  - 完成后无匹配条件时返回空列表，匹配条件返回可回溯到推荐和命中案例的明细。
  - _Requirements: 3.1, 3.2, 4.1, 4.4, 4.5_
  - _Boundary: FeedbackRepository_
  - _Depends: 2.3_

- [x] 3.3 (P) 实现单次推荐运行反馈查询
  - 根据推荐运行标识返回运行级反馈和该运行下各推荐项反馈。
  - 保持运行级和推荐项级反馈的目标级别清晰可区分。
  - 返回运行级和推荐项级均可回溯的推荐引用与审计字段，并包含关联查询上下文摘要（`query_hash`、过滤条件摘要、候选数量、返回数量）。
  - 完成后管理员可以查看一次推荐运行下的全部反馈记录。
  - _Requirements: 3.1, 4.2, 4.4, 4.5_
  - _Boundary: FeedbackService, FeedbackRepository_
  - _Depends: 2.3_

- [x] 3.4 (P) 实现基础统计查询
  - 计算反馈数量、有用率及有用性分布（useful/not_useful/unknown），并支持按推荐运行、案例和时间范围聚合。
  - 统计响应支持按口径拆分的 `not_useful` 占比和 `unknown` 占比。
  - 空结果返回零值统计，不返回错误。
  - 完成后质量分析者可以通过 API 读取 MVP 所需基础质量指标。
  - _Requirements: 4.3, 4.4, 5.5_
  - _Boundary: FeedbackStatsService_
  - _Depends: 2.3_

- [x] 4. 暴露 API 并接入应用

- [x] 4.1 暴露反馈提交 API
  - 提供推荐反馈提交入口，接收推荐运行标识、可选推荐项标识、有用性、备注和来源渠道。
  - 将字段错误、目标错误和系统错误映射为稳定 HTTP 响应。
  - 完成后客户端可提交运行级或推荐项级反馈，并获得反馈标识和保存结果。
  - _Requirements: 1.1, 1.3, 1.4, 5.1_
  - _Boundary: FeedbackRouter_
  - _Depends: 2.4_

- [x] 4.2 暴露反馈删除 API
  - 提供反馈删除入口，支持按 `feedback_id`、`case_id`、`recommendation_run_id`、`recommendation_item_id` 删除反馈（至少一个过滤条件）。
  - 返回稳定删除结果：`success`、`deleted_count`、`deleted_at`；未命中返回 `deleted_count=0` 且不报错。
  - 校验 `reason`、`requested_by` 的必填和枚举有效性，并在日志与响应中遵循隐私约束。
  - 完成后案例删除可触发反馈删除，定时清理程序可删除无效记录。
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - _Boundary: FeedbackRouter_
  - _Depends: 3.1_

- [x] 4.3 (P) 暴露手动清理触发 API
  - 提供 `POST /api/admin/cleanup/feedback` 管理端点，触发一次清理执行并返回 `CleanupResult`（`success`、`scanned_count`、`deleted_count`、`duration_ms`）。
  - 校验请求参数固定约束：`reason=schedule_deleted`、`requested_by=system`。
  - 失败时返回稳定错误并记录脱敏日志，不影响反馈提交、查询与统计主流程。
  - 完成后运维可手动触发无效反馈清理并获得可观测结果。
  - _Requirements: 6.5, 6.4, 5.1, 5.2_
  - _Boundary: FeedbackRouter, FeedbackCleanupService_
  - _Depends: 3.1_

- [x] 4.4 暴露反馈查询和统计 API
  - 提供反馈明细查询、推荐运行反馈查询和基础统计查询入口。
  - 查询响应包含必要推荐引用字段，但不返回完整案例正文、向量数组或不必要敏感信息。
  - 完成后管理员可以通过 HTTP 查询反馈明细、运行反馈和基础统计。
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.2, 5.5_
  - _Boundary: FeedbackRouter, FeedbackStatsService_
  - _Depends: 3.2, 3.3, 3.4_

- [x] 4.5 接入应用入口、数据库会话和错误映射
  - 注册反馈路由，纳入数据库 metadata、迁移、请求事务生命周期和统一错误映射。
  - 确认提交、删除、查询和统计路径使用统一响应结构和脱敏日志。
  - 只追加路由注册、metadata 导入和错误码映射，不重构共享应用入口、数据库会话或错误映射基础设施。
  - 完成后从应用入口发起请求即可访问推荐反馈端点。
  - _Requirements: 2.4, 5.1, 5.2_
  - _Boundary: FeedbackRouter, ErrorMapper_
  - _Depends: 4.1, 4.2, 4.3, 4.4_

- [x] 4.6 验证推荐、案例和向量边界分离
  - 确认反馈路径只读取推荐标识，不触发检索、重排、解释、案例更新、向量更新或推荐运行写回。
  - 确认反馈数据出口只供后续分析读取，不在本规格内驱动自动排序学习。
  - 完成后本规格与上游推荐和后续优化规格可独立验证。
  - _Requirements: 1.5, 3.4, 5.5_
  - _Boundary: FeedbackService, RecommendationReferenceResolver_
  - _Depends: 4.5_

- [x] 5. 补齐验证覆盖

- [x] 5.1 编写反馈提交和幂等测试
  - 覆盖运行级反馈（`recommendation_item_id` 为 None）、推荐项级反馈、重复提交、并发提交、非法枚举和备注过长。
  - 断言同一用户同一反馈目标最终只有一条最新记录。
  - 断言数据库唯一约束保证并发提交的幂等性。
  - 完成后反馈提交、字段约束和幂等规则可被自动化测试稳定验证。
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 2.4, 5.3, 5.4_
  - _Boundary: FeedbackSchemas, FeedbackRepository, FeedbackService_

- [x] 5.2 编写推荐引用解析和边界测试
  - 覆盖推荐运行不存在、推荐项不存在、推荐项不属于运行和成功解析引用。
  - 断言反馈提交不调用推荐检索、重排、解释生成，也不写回案例、向量或推荐记录。
  - 完成后推荐引用解析和边界分离可被自动化测试稳定验证。
  - _Requirements: 1.2, 1.4, 1.5, 3.4, 3.5_
  - _Boundary: RecommendationReferenceResolver, FeedbackService_

- [x] 5.3 编写删除、查询、统计和隐私测试
  - 覆盖反馈删除、明细过滤、运行反馈查询、空结果、基础统计、有用率和有用性分布。
  - 覆盖删除接口 `feedback_id` 过滤、未命中幂等删除（`deleted_count=0`）和删除响应字段完整性（`success`、`deleted_count`、`deleted_at`）。
  - 覆盖手动清理触发接口 `POST /api/admin/cleanup/feedback` 的参数约束与 `CleanupResult` 响应字段（`success`、`scanned_count`、`deleted_count`、`duration_ms`）。
  - 覆盖明细/运行查询返回关联上下文字段（`query_hash`、过滤条件摘要、候选数量、返回数量）及推荐项详细字段来自关联查询。
  - 断言日志、错误响应和统计结果不包含完整备注或敏感门店信息。
  - 完成后反馈删除、查询、统计出口和隐私要求均有自动化验证。
  - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: FeedbackRepository, FeedbackStatsService, ErrorMapper_
