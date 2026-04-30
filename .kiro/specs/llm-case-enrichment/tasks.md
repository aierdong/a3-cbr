# Implementation Plan

- [ ] 1. 建立 LLM 增强基础设施

- [ ] 1.1 扩展运行配置和错误码
  - 增加 LLM 供应商、模型、超时、重试次数、生产隐私确认和启用开关配置。
  - 增加上游契约门控配置：`case_contract_version`、`mapping_version`，并定义不匹配错误码 `CASE_INPUT_CONTRACT_MISMATCH`。
  - 增加 LLM 增强相关错误码，覆盖案例不可增强、输出校验失败、供应商失败和隐私配置缺失。
  - 仅向共享配置和错误映射追加本规格所需配置值与错误码，不拥有 `backend/app/core/config.py`、`backend/app/core/errors.py` 或 `ErrorMapper` 基础实现。
  - 完成后应用可在配置缺失时 fail closed，并返回稳定错误结构。
  - _Requirements: 1.2, 1.5, 6.3, 6.4, 6.5_

- [ ] 1.2 建立派生结果和运行记录迁移
  - 创建案例增强结果、案例增强运行记录和推荐文案运行记录的数据结构。
  - 为运行记录补充 `request_purpose`、`input_contract_version`、`mapping_version` 字段，用于审计与契约追溯。
  - 数据结构通过 `case_id` 关联上游案例，不修改案例基础表，不包含向量或相似度字段；`RecommendationCopyRun` 仅记录 LLM 调用审计、成本和 schema 校验结果，不作为推荐运行、召回或排序持久化记录。
  - 完成后测试数据库可以应用迁移并查询到新增表和索引。
  - _Requirements: 2.4, 2.5, 4.2, 4.3, 4.4, 4.5, 6.3_

- [ ] 1.3 定义 LLM 增强请求响应和状态契约
  - 定义案例增强运行、当前增强状态、人工审核、推荐文案请求响应和错误响应契约。
  - 定义派生结果状态、运行状态、审核状态和输出版本字段。
  - 在 `CaseEnrichmentOutput` 中固化 `missing_information[]` 结构（`field`、`reason`、`blocking_level`），用于“信息不足”场景的标准返回。
  - 完成后 API、服务和测试可复用同一套 schema 表达发布、失败、待审核和过期状态。
  - _Requirements: 1.3, 1.4, 2.3, 3.4, 4.1, 4.4, 4.5, 5.1, 5.2, 5.3, 5.5_

- [ ] 2. 实现案例增强核心能力

- [ ] 2.1 (P) 实现上游案例快照读取
  - 通过上游案例管理能力读取案例标识、基础字段、状态、过滤字段和更新时间。
  - 增加运行时契约握手检查：上游契约版本与本服务 `case_contract_version`/`mapping_version` 不匹配时直接拒绝运行。
  - 明确输入状态门控：仅 `active`、`archived` 可进入增强流程，`draft` 请求直接拒绝并返回可识别原因。
  - 将案例正文裁剪为 LLM 任务所需输入，排除向量、推荐分值、反馈和未授权扩展字段。
  - 完成后不存在或不可作为输入的案例会被拒绝，并返回可识别原因。
  - _Requirements: 1.1, 1.2, 1.5, 6.1_
  - _Boundary: CaseSnapshotProvider_

- [ ] 2.2 (P) 实现 Prompt 模板和安全约束
  - 为案例增强和推荐文案分别定义固定 Prompt 模板和结构化输出指令。
  - 在 Prompt 中声明忽略案例正文里的指令性内容，只抽取业务事实并禁止编造。
  - 完成后每类 LLM 任务都有明确输出 schema、来源引用和提示词注入防护约束。
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 5.1, 6.2_
  - _Boundary: PromptCatalog_

- [ ] 2.3 (P) 实现 LLM 客户端适配
  - 接入 `deepseek-v4-pro` 或兼容模型配置，统一处理超时、限流、供应商错误和不可解析响应。
  - 记录供应商、模型、`request_purpose`、任务类型、状态和错误类型，不记录完整案例正文。
  - 完成后 LLM 调用可通过 fake client 或 mock client 在测试中稳定替换。
  - _Requirements: 4.2, 6.3, 6.4, 6.5_
  - _Boundary: LLMClient_

- [ ] 2.4 (P) 实现 LLM 输出校验
  - 校验摘要、结构化建议、标签建议、来源引用、推荐文案和候选引用是否符合 schema。
  - 在摘要或推荐文案不可可靠生成时，强制输出 `missing_information[]`，并阻止“空理由但宣称成功”的结果发布。
  - 对标签建议执行去空、去重、数量限制和越界处理。
  - 完成后无法解析、字段缺失、非法枚举或候选引用不匹配的输出不会被发布。
  - _Requirements: 2.3, 3.2, 3.3, 4.1, 4.2, 5.2, 5.3_
  - _Boundary: OutputValidator_

- [ ] 2.5 实现派生结果和运行记录持久化
  - 保存案例增强运行的开始、成功、失败、校验失败和可重试状态。
  - 保存 `request_purpose`、`input_contract_version`、`mapping_version`，保证审计与问题追溯可查询。
  - 保存当前派生结果、案例输入更新时间、输出版本、来源引用和审核状态。
  - 完成后可以按 `case_id` 查询当前可用结果，并按 `run_id` 查询失败原因和重试状态。
  - _Requirements: 1.3, 2.4, 3.4, 4.2, 4.3, 4.4, 4.5, 6.3_
  - _Boundary: EnrichmentRepository_

- [ ] 2.6 实现案例增强服务编排
  - 编排案例快照读取、Prompt 构造、LLM 调用、输出校验、结果保存和失败记录。
  - 内容不足时返回缺失信息说明，不生成或发布编造摘要。
  - 完成后合法案例可以生成问题摘要、方案摘要、结构化字段建议和标签建议，且不修改案例基础字段。
  - _Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 3.5, 4.3_
  - _Boundary: EnrichmentService_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 2.7 实现同步运行和重试边界
  - 为增强运行提供同步执行入口、状态返回和可重试失败的重试入口。
  - 限制重试次数，只允许供应商或临时失败进入重试流程。
  - 完成后 LLM 失败不会阻塞案例基础查看，重试会更新运行记录和错误状态。
  - _Requirements: 1.4, 4.2, 4.4, 6.4_
  - _Boundary: EnrichmentJobRunner_
  - _Depends: 2.6_

- [ ] 3. 实现推荐文案生成能力

- [ ] 3.1 实现推荐候选文案服务
  - 接收当前问题、已排序候选案例和候选来源信息，生成推荐理由、参考解决点和注意事项。
  - 保留输入候选顺序和 `case_id` 引用，不新增候选、不过滤候选、不改变相似度或排序。
  - 记录的文案运行仅用于 LLM 调用审计、成本和 schema 校验追踪；推荐运行和推荐项快照仍由 CBR 推荐规格持久化。
  - 完成后每个可解释候选都有一条可追溯文案；信息不足时通过 `missing_information[]` 返回无法生成原因。
  - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - _Boundary: RecommendationCopyService_
  - _Depends: 2.2, 2.3, 2.4_

- [ ] 3.2 实现推荐文案失败降级响应
  - 为 LLM 失败、校验失败、候选信息不足和部分候选失败定义响应结构。
  - 保证下游推荐流程可以继续展示结构化候选信息，而不依赖 LLM 文案成功。
  - 完成后推荐文案接口失败不会产生排序副作用，并能返回稳定降级信息。
  - _Requirements: 5.3, 5.4, 5.5, 6.4_
  - _Boundary: RecommendationCopyService, ErrorMapper_
  - _Depends: 3.1_

- [ ] 4. 暴露 API 并接入应用

- [ ] 4.1 实现案例增强 API
  - 暴露创建增强运行、查询当前增强状态、审核派生结果和重试运行接口。
  - 成功响应包含 `run_id`、派生结果状态、输出版本和上游案例更新时间。
  - 完成后客户端可通过 HTTP 触发增强、查看状态、提交人工审核和执行允许的重试。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.4, 4.4, 4.5, 6.4_
  - _Boundary: EnrichmentRouter_
  - _Depends: 2.7_

- [ ] 4.2 实现推荐文案 API
  - 暴露推荐文案生成接口，接收当前问题和已排序候选列表。
  - 响应按输入候选顺序返回解释文案或降级原因，不包含排序或相似度修改字段。
  - 完成后 CBR 推荐流程可调用该接口获取可解释文案。
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: EnrichmentRouter_
  - _Depends: 3.2_

- [ ] 4.3 接入应用入口和数据库会话
  - 将 enrichment 路由注册到后端应用入口，并纳入数据库 metadata。
  - 为增强运行、审核和推荐文案生成提供事务提交和失败回滚行为。
  - 只追加路由注册、metadata 导入和本模块事务使用，不重构共享应用入口或数据库会话基础设施。
  - 完成后从应用入口发起 HTTP 请求可以访问全部 LLM 增强端点。
  - _Requirements: 4.2, 4.3, 4.4, 6.3_
  - _Boundary: EnrichmentRouter, EnrichmentRepository_
  - _Depends: 4.1, 4.2_

- [ ] 4.4 验证与上游和下游边界分离
  - 检查代码路径不会修改 `a3_cases` 基础字段，也不会生成 embedding、向量索引、相似度或排序决策。
  - 确认已发布派生结果可被下游按状态消费，失败、待审核和过期结果不会被误当成可发布内容。
  - 完成后本规格边界与案例管理、向量索引和 CBR 推荐保持一致。
  - _Requirements: 1.1, 1.5, 2.5, 3.5, 4.3, 4.4, 5.4_
  - _Boundary: EnrichmentService, RecommendationCopyService_
  - _Depends: 4.3_

- [ ] 5. 补齐验证覆盖

- [ ] 5.1 编写输出校验和 Prompt 安全单元测试
  - 覆盖 JSON 解析失败、字段缺失、枚举越界、标签规范化、来源引用缺失和候选引用不匹配。
  - 覆盖 `missing_information[]` 契约：信息不足时必须返回结构化原因，且不得发布伪成功结果。
  - 覆盖案例正文中包含提示词注入文本时仍按固定 schema 输出和校验。
  - 完成后输出校验和 Prompt 安全边界可独立通过测试验证。
  - _Requirements: 2.3, 3.3, 4.1, 4.2, 5.2, 5.3, 6.2_
  - _Boundary: OutputValidator, PromptCatalog_

- [ ] 5.2 编写案例增强服务和持久化测试
  - 覆盖成功生成、内容不足、上游案例不存在、`draft` 状态拒绝、结果过期、审核覆盖、失败记录和可重试状态。
  - 断言所有派生内容保存在独立结构中，不反写案例基础字段。
  - 完成后案例增强核心流程可用 mock LLM 和测试数据库稳定验证。
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.5, 3.1, 3.4, 3.5, 4.3, 4.4, 4.5_
  - _Boundary: EnrichmentService, EnrichmentRepository_
  - _Depends: 2.7_

- [ ] 5.3 编写推荐文案测试
  - 覆盖完整候选、候选信息不足、LLM 失败、部分失败和输出候选顺序校验。
  - 断言接口不会返回排序变更、相似度变更、过滤结果或新增候选。
  - 完成后推荐文案能力可与 CBR 推荐边界安全集成。
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: RecommendationCopyService_
  - _Depends: 3.2_

- [ ] 5.4 编写 API 与安全隐私集成测试
  - 覆盖增强运行创建、状态查询、审核、重试、推荐文案和统一错误响应。
  - 覆盖上游契约版本不匹配时的 fail-closed 行为与 `CASE_INPUT_CONTRACT_MISMATCH` 返回。
  - 覆盖运行记录审计字段（`request_purpose`、`input_contract_version`、`mapping_version`）写入和查询。
  - 覆盖生产隐私配置缺失、供应商超时、限流和日志脱敏。
  - 完成后 API 层、错误结构、隐私门控和失败降级都有端到端验证。
  - _Requirements: 1.4, 1.5, 3.4, 4.2, 4.4, 5.5, 6.1, 6.3, 6.4, 6.5_
  - _Boundary: EnrichmentRouter, LLMClient, ErrorMapper_
  - _Depends: 4.3_
