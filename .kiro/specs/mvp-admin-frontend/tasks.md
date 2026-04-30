# Implementation Plan

- [ ] 1. 建立前端应用基础
- [ ] 1.1 创建 Vue 3 前端应用脚手架
  - 建立 TypeScript、构建、测试和基础入口配置。
  - 配置应用启动入口，使根组件可以挂载后台布局和路由。
  - 完成后，开发环境能够启动空后台页面，测试命令能够执行基础测试。
  - _Requirements: 1.1, 1.5, 6.5_
  - _Boundary: frontend package, main.ts, App.vue, router_

- [ ] 1.2 建立后台路由、布局和基础样式
  - 配置案例列表、案例创建、案例编辑、案例详情和推荐检索页面路由。
  - 提供案例管理与检索推荐导航，并隐藏越界菜单入口。
  - 完成后，用户可以在各页面间切换，并看到当前位置和返回路径。
  - _Requirements: 1.1, 1.2, 1.3, 1.5_
  - _Boundary: AdminLayout, router, base.css_

- [ ] 1.3 建立通用请求状态和错误展示能力
  - 定义加载中、成功、空结果、字段校验失败、未找到、状态冲突、降级成功和系统失败的前端状态。
  - 提供通用加载、空状态、错误提示和重试展示组件。
  - 完成后，任一页面请求失败都能展示可理解提示，而不是空白页面。
  - _Requirements: 1.4, 6.2, 6.4_
  - _Boundary: ApiClient, LoadingState, EmptyState, ErrorNotice, useAsyncState_

- [ ] 2. 实现案例管理页面
- [ ] 2.1 (P) 实现案例 API 契约映射
  - 定义案例列表项、案例详情、创建请求、编辑请求、分页响应和字段错误类型。
  - 封装创建、编辑、详情和列表查询调用，并统一使用通用错误模型。
  - 完成后，页面可以通过单一案例服务消费案例管理接口。
  - _Requirements: 2.1, 2.2, 2.4, 3.3, 6.1, 6.3_
  - _Boundary: CaseApiService, ApiClient_
  - _Depends: 1.3_

- [ ] 2.2 实现案例列表、筛选和分页展示
  - 展示案例标识、问题描述预览、品牌、门店、问题类型、状态、标签、创建时间和更新时间。
  - 支持按品牌、门店、问题类型、标签、状态和创建时间范围提交筛选。
  - 完成后，列表空结果展示空状态和有效分页信息。
  - _Requirements: 2.1, 2.2, 2.3, 2.5_
  - _Boundary: CaseListPage, CaseFilterBar, CaseTable, useCases_

- [ ] 2.3 实现案例详情页
  - 展示完整问题描述、场景上下文、根因分析、解决步骤、效果结果、标签和状态。
  - 排除向量数组、推荐运行、反馈表内部字段和后端诊断信息。
  - 完成后，用户从列表打开案例可看到完整基础字段并能返回列表。
  - _Requirements: 1.2, 2.4, 2.5_
  - _Boundary: CaseDetailPage, CaseDetailPanel, useCases_

- [ ] 2.4 实现案例创建和编辑表单
  - 支持录入问题描述、品牌信息、门店信息、问题类型、场景上下文、根因分析、解决步骤、效果结果和标签。
  - 编辑模式加载当前案例并阻止修改案例标识和创建时间。
  - 完成后，合法提交展示案例标识、状态和更新时间；字段错误展示在对应区域并保留可修改内容。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: CaseCreatePage, CaseEditPage, CaseForm, useCases_

- [ ] 3. 实现推荐检索与结果展示
- [ ] 3.1 (P) 实现推荐 API 契约映射
  - 定义推荐请求、过滤条件、推荐运行元数据、推荐项、分值、解释状态和降级状态类型。
  - 封装相似案例检索调用，并保持后端返回的推荐项顺序。
  - 完成后，推荐页面可以通过单一推荐服务消费检索推荐接口。
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.3_
  - _Boundary: RecommendationApiService, ApiClient_
  - _Depends: 1.3_

- [ ] 3.2 实现检索输入和过滤条件表单
  - 支持当前问题文本、Top-K 参数和品牌、门店、问题类型、标签、案例状态、创建时间范围等过滤条件；不展示未列入上游契约的过滤字段。
  - 提交时展示加载状态，并在输入错误时显示字段级提示。
  - 完成后，用户可以提交一次完整检索请求并看到实际过滤条件回显。
  - _Requirements: 4.1, 4.2, 6.2_
  - _Boundary: RecommendationPage, RecommendationSearchForm, useRecommendations_

- [ ] 3.3 实现推荐运行摘要和推荐项卡片
  - 展示推荐运行标识、检索状态、候选数量、返回数量、降级原因和缺失字段提示。
  - 展示推荐项标识、案例标识、排序位置、案例引用、核心步骤、效果摘要、向量相似度、语义相似度、业务参数分、最终聚合分、推荐理由、参考点、注意事项、来源引用和解释状态。
  - 完成后，空结果、候选不足、重排降级和解释降级都能保留可用内容并清楚展示状态。
  - _Requirements: 4.2, 4.3, 4.4, 4.5_
  - _Boundary: RecommendationPage, RecommendationSummary, RecommendationCard, useRecommendations_

- [ ] 4. 实现推荐反馈控件
- [ ] 4.1 (P) 实现反馈 API 契约映射
  - 定义反馈提交请求、反馈响应、有用性、评分、采纳状态、来源渠道和幂等键类型。
  - 封装推荐反馈提交调用，并将反馈错误映射为局部控件状态。
  - 完成后，反馈控件可以通过单一反馈服务提交运行级和推荐项级反馈。
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.3_
  - _Boundary: FeedbackApiService, ApiClient_
  - _Depends: 1.3_

- [ ] 4.2 实现运行级反馈控件
  - 在推荐运行区域提供有用性、1-5 评分、采纳状态和备注输入。
  - 提交时携带推荐运行标识并使用后台来源渠道。
  - 完成后，运行级反馈成功时展示保存状态，失败时推荐结果仍然可见。
  - _Requirements: 5.1, 5.3, 5.4, 5.5_
  - _Boundary: FeedbackControls, useFeedback_

- [ ] 4.3 实现推荐项级反馈控件
  - 在每条推荐项中提供有用性、1-5 评分、采纳状态和备注输入。
  - 提交时携带推荐运行标识和推荐项标识。
  - 完成后，单条推荐项反馈状态只影响对应控件，不改变推荐排序、案例内容或解释。
  - _Requirements: 5.2, 5.3, 5.4, 5.5_
  - _Boundary: FeedbackControls, RecommendationCard, useFeedback_

- [ ] 5. 完成页面集成与验证
- [ ] 5.1 集成案例、推荐和反馈页面闭环
  - 将案例页面、推荐页面和反馈控件接入后台布局与路由。
  - 确认案例创建、列表查看、详情查看、检索推荐和反馈提交可以连续操作。
  - 完成后，用户能从后台导航完成一次 MVP 验证闭环。
  - _Requirements: 1.1, 1.2, 2.1, 2.4, 3.3, 4.2, 5.3_
  - _Boundary: AdminLayout, CaseListPage, CaseCreatePage, CaseEditPage, CaseDetailPage, RecommendationPage, FeedbackControls_

- [ ] 5.2 验证错误、隐私和边界行为
  - 覆盖字段校验失败、未找到、状态冲突、空结果、降级推荐、系统失败和反馈失败场景。
  - 确认页面、日志和浏览器持久化状态不暴露完整案例正文、完整查询文本、向量数组、完整备注或供应商原始错误。
  - 完成后，所有边界失败都有可观察页面反馈，且不会扩大前端职责。
  - _Requirements: 1.4, 2.5, 3.4, 4.4, 5.4, 6.2, 6.4, 6.5_
  - _Boundary: ApiClient, ErrorNotice, useAsyncState, useRecommendations, useFeedback_

- [ ] 5.3 补充前端组件和页面测试
  - 覆盖 API 契约映射、案例表单、案例列表空状态、推荐项展示、降级提示和反馈控件。
  - 覆盖从检索推荐到反馈提交的页面级交互。
  - 完成后，测试能够证明所有需求编号至少被一个页面或组件行为覆盖。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: API service tests, component tests, page tests_
