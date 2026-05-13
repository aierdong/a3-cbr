# Requirements Document

## Introduction

`mvp-admin-frontend` 为业务、产品、督导和后台验证人员提供 Vue 3 基础后台入口，用于完成 MVP 的案例录入、案例查看、相似案例检索、推荐结果观察和反馈提交闭环。当前仓库已有后端规格定义案例管理、检索推荐和推荐反馈契约，但还没有前端应用、页面路由、表单、列表、推荐展示和反馈控件规格。

本规格依赖 `a3-case-management`、`cbr-retrieval-recommendation` 和 `recommendation-feedback` 的稳定 API 与数据契约，展示部分 `llm-case-enrichment` 生成或降级后的推荐解释内容。前端只消费后端能力，不拥有案例持久化、检索排序、LLM 生成或反馈存储职责。

## Boundary Context

- **In scope**: Vue 3 基础后台页面、案例列表、案例详情、案例创建与编辑表单、相似案例检索输入、Top-K 推荐结果展示、推荐理由与相似度展示、运行级和推荐项级反馈控件、基础加载状态和错误提示。
- **Out of scope**: 后端持久化、案例字段规则扩展、向量检索、CBR 重排、LLM 文案生成、反馈学习排序、复杂权限、经营数据看板、消息推送、邮件推送、品牌多租户管理、移动端深度适配。
- **Adjacent expectations**: 后端规格提供稳定案例、推荐和反馈 API。若上游字段、路径、状态或错误结构变化，本规格必须重新校验页面数据映射；前端不得为展示便利要求后端新增非 MVP 数据模型。

## Requirements

### Requirement 1: 基础后台导航与页面入口

**Objective:** As a 业务或产品验证人员, I want 一个清晰的后台入口访问案例和推荐验证页面, so that 我可以连续完成 MVP 验证闭环。

#### Acceptance Criteria

1.1 When 用户打开后台前端, the MVP 后台前端 shall 展示案例管理和检索推荐的基础导航入口。
1.2 When 用户在案例列表、案例详情、案例表单和检索推荐页面之间切换, the MVP 后台前端 shall 保持清晰的当前位置提示和返回路径。
1.3 The MVP 后台前端 shall 避免展示经营看板、消息推送、权限配置、行业库审核或其它超出 MVP 边界的菜单入口。
1.4 If 目标页面暂时无法加载所需数据, then the MVP 后台前端 shall 展示可理解的失败提示和重试入口，而不是空白页面。
1.5 The MVP 后台前端 shall 使用后台页面形式覆盖桌面端验证场景，不承诺移动端深度适配体验。

### Requirement 2: 案例列表与详情查看

**Objective:** As a 督导、后台管理者或产品验证人员, I want 浏览和查看 A3 案例基础信息, so that 我可以复盘历史案例并选择可用于推荐验证的数据。

#### Acceptance Criteria

2.1 When 用户进入案例列表页, the MVP 后台前端 shall 展示案例标识、问题描述预览、品牌、门店、问题类型、状态、标签、创建时间和更新时间等列表字段。
2.2 When 用户设置品牌、门店、问题类型、标签、状态或创建时间范围筛选条件, the MVP 后台前端 shall 按用户输入请求案例列表并展示实际结果。
2.3 When 案例列表没有匹配结果, the MVP 后台前端 shall 展示空状态和有效分页信息。
2.4 When 用户打开某个案例详情, the MVP 后台前端 shall 展示该案例的完整基础字段、场景上下文、根因分析、解决步骤、效果结果、标签和状态。
2.5 The MVP 后台前端 shall 不在案例列表或详情中展示向量数组、内部推荐运行记录、反馈表内部字段或未授权的后端诊断信息。

### Requirement 3: 案例创建与编辑表单

**Objective:** As a 督导或后台管理者, I want 在后台录入和修改 A3 案例, so that MVP 能持续积累可检索案例数据。

#### Acceptance Criteria

3.1 When 用户新建案例, the MVP 后台前端 shall 提供问题描述、品牌信息、门店信息、问题类型、场景上下文、根因分析、解决步骤、效果结果和标签输入能力。
3.2 When 用户编辑已有案例, the MVP 后台前端 shall 加载案例当前基础字段，并阻止用户修改案例标识和创建时间。
3.3 When 用户提交案例表单, the MVP 后台前端 shall 将表单数据提交给案例管理能力，并展示成功后的案例标识、状态和更新时间。
3.4 If 后端返回字段级校验错误、未找到或状态冲突, then the MVP 后台前端 shall 在对应字段或页面区域展示错误信息，并保留用户可修改的已输入内容。
3.5 The MVP 后台前端 shall 不要求 LLM 增强、向量索引或推荐流程先完成，才能创建或编辑案例。
3.6 When 用户选择「提交且摘要」且案例保存接口返回成功, the MVP 后台前端 shall 随后调用 `POST /api/a3-cases/{case_id}/enrichment-runs` 触发增强运行，且不等待增强任务完成或轮询增强结果；若该触发请求失败，则向用户展示失败原因并提供重试触发入口，已保存的案例数据仍保持可访问。

### Requirement 4: 相似案例检索输入与推荐展示

**Objective:** As a 门店用户、督导或产品验证人员, I want 输入新问题并查看 Top-K 相似案例推荐, so that 我能判断 CBR 推荐质量是否满足 MVP 验证目标。

#### Acceptance Criteria

4.1 When 用户提交相似案例检索请求, the MVP 后台前端 shall 支持输入当前问题文本、Top-K 参数和基础过滤条件。
4.2 When 推荐接口返回成功结果, the MVP 后台前端 shall 展示推荐运行标识、检索状态、实际过滤条件、候选数量、返回数量和每条推荐项。
4.3 The MVP 后台前端 shall 在每条推荐项中展示推荐项标识、案例标识、排序位置、案例引用信息、核心解决步骤、效果摘要、向量相似度、语义相似度、业务参数分、最终聚合分、推荐理由、可参考解决点、注意事项、来源引用和解释状态。
4.4 If 推荐结果为空、候选不足、重排降级或解释降级, then the MVP 后台前端 shall 显示后端返回的状态、原因或缺失字段提示，并继续展示可用推荐内容。
4.5 The MVP 后台前端 shall 不在前端本地重新排序推荐项、重新计算相似度或生成推荐理由。

### Requirement 5: 推荐反馈控件

**Objective:** As a 推荐结果查看者, I want 对整次推荐或具体推荐项提交基础反馈, so that 团队可以收集推荐质量信号。

#### Acceptance Criteria

5.1 When 用户查看推荐运行结果, the MVP 后台前端 shall 提供运行级反馈入口，支持有用性（useful/not_useful/unknown）和备注。
5.2 When 用户查看单条推荐项, the MVP 后台前端 shall 提供推荐项级反馈入口，并携带对应推荐运行标识和推荐项标识提交。
5.3 When 反馈提交成功, the MVP 后台前端 shall 展示保存后的反馈状态或更新时间，避免用户误以为反馈未记录。
5.4 If 反馈提交失败, then the MVP 后台前端 shall 展示稳定错误提示，并保持推荐结果仍然可见。
5.5 The MVP 后台前端 shall 不基于反馈结果改变当前推荐排序、案例内容或推荐解释。

### Requirement 6: API 契约、状态处理与 MVP 边界

**Objective:** As a 前端实现者和规格评审者, I want 前端行为严格依赖既有后端契约, so that 后端、推荐和反馈职责不会被页面实现反向扩大。

#### Acceptance Criteria

6.1 The MVP 后台前端 shall 只通过已定义的案例、推荐和反馈接口读取或提交数据。
6.2 The MVP 后台前端 shall 对加载中、成功、空结果、字段校验失败、未找到、状态冲突、降级成功和系统失败等状态提供可观察页面反馈。
6.3 If 上游 API 路径、字段名称、枚举值、状态语义或错误结构变化, then the MVP 后台前端 shall 重新校验页面映射后再继续实施。
6.4 The MVP 后台前端 shall 避免在日志、页面错误提示或浏览器持久化状态中暴露完整敏感案例正文、完整查询文本、向量数组或供应商原始错误。
6.5 The MVP 后台前端 shall 保持 MVP 轻量边界，不引入复杂设计系统、复杂权限框架、离线缓存、消息系统或移动端专属流程作为本规格交付条件。
