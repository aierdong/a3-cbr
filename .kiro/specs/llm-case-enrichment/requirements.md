# Requirements Document

## Introduction

`llm-case-enrichment` 为 A3 案例和相似案例推荐结果提供 LLM 增强能力。当前 MVP 已把案例基础数据边界交给 `a3-case-management`，并明确 LLM 只负责摘要、结构化提取、标签建议和推荐文案生成，不承担主检索、向量索引或 CBR 排序职责。本规格稳定 LLM 输出、校验、失败处理和隐私安全要求，让后续向量索引、CBR 推荐和后台页面可以消费受控的 AI 派生内容。

## Boundary Context

- **In scope**: 基于 A3 案例基础字段生成问题摘要、方案摘要、结构化字段建议、标签建议和推荐理由文案；定义结构化输出约束、校验、派生结果状态、失败记录、重试边界和隐私安全要求。
- **Out of scope**: A3 案例 CRUD、案例基础字段生命周期、embedding 生成、pgvector 索引、reranker Top-K 召回、CBRKit 重排、相似度计算、反馈学习排序、复杂多轮追问、模型微调和本地大模型部署。
- **Adjacent expectations**: 本规格消费 `a3-case-management` 提供的 `case_id`、基础字段、状态、过滤字段和时间戳；`case-vector-indexing` 可消费已校验的摘要或规范化文本；`cbr-retrieval-recommendation` 可消费推荐文案生成能力，但召回和排序规则不由本规格决定。

## Requirements

### Requirement 1: 案例 LLM 增强输入与触发

**Objective:** As a 督导或后台管理者, I want 系统基于已存在的 A3 案例生成 AI 派生内容, so that 案例入库后可以获得一致的摘要和结构化建议。

#### Acceptance Criteria

1.1 When 用户或下游流程请求对某个案例执行 LLM 增强, the LLM 案例增强服务 shall 只读取 `a3-case-management` 已定义的案例标识、基础字段、状态、过滤字段和更新时间作为输入，且仅允许状态为 `active` 或 `archived` 的案例进入增强流程。
1.2 If 请求引用的案例不存在、状态为 `draft` 或因其他原因不可作为增强输入, then the LLM 案例增强服务 shall 拒绝处理并返回可识别的失败原因。
1.3 When 案例基础内容在上次增强后发生变化, the LLM 案例增强服务 shall 能识别既有派生结果已过时并允许重新生成。
1.4 The LLM 案例增强服务 shall 不要求案例创建或编辑流程等待 LLM 增强完成。

### Requirement 2: 问题摘要与方案摘要生成

**Objective:** As a 门店用户或督导, I want 查看一致、简洁的案例摘要, so that 我可以快速理解历史问题、根因、处理方式和改善结果。

#### Acceptance Criteria

2.1 When 案例包含可用的问题描述、场景上下文和根因分析, the LLM 案例增强服务 shall 生成问题摘要，概括问题现象、发生场景和主要根因。
2.2 When 案例包含解决步骤和效果结果, the LLM 案例增强服务 shall 生成方案摘要，概括关键处理步骤和可观察改善结果。
2.3 If 案例内容不足以生成可信摘要, then the LLM 案例增强服务 shall 返回缺失信息说明而不是编造摘要。
2.4 The LLM 案例增强服务 shall 保留摘要与原始案例内容的来源关联，便于后续追溯。
2.5 The LLM 案例增强服务 shall 将 AI 摘要作为派生内容保存，不直接替换用户录入的原始案例字段。

### Requirement 3: 结构化提取与标签建议

**Objective:** As a 后台管理者, I want LLM 从自然语言案例中提出结构化字段和标签建议, so that 案例归集和后续检索展示更加一致。

#### Acceptance Criteria

3.1 When 案例内容可分析, the LLM 案例增强服务 shall 输出问题类型建议、根因分类建议、适用场景建议和标签建议。
3.2 The LLM 案例增强服务 shall 区分已由案例管理系统提供的基础字段和 LLM 推断出的建议字段。
3.3 If LLM 输出的标签列表为空、重复、包含无效标签、越界或不符合标签规则, then the LLM 案例增强服务 shall 按规则拒绝或规范化标签，并在输出里说明处理结果。
3.4 The LLM 案例增强服务 shall 不把结构化建议反写为案例基础字段，除非后续明确的人工编辑流程在案例管理边界内完成。

### Requirement 4: 结构化输出校验与派生结果状态

**Objective:** As a 下游功能实现者, I want LLM 输出先通过结构化校验再被消费, so that 向量索引、推荐展示和后台页面不会依赖不可解析或不可信的文本。

#### Acceptance Criteria

4.1 When LLM 返回增强结果, the LLM 案例增强服务 shall 按预定义 schema 校验字段、类型、必填项、枚举值和长度限制。
4.2 If LLM 输出无法解析或 schema 校验失败, then the LLM 案例增强服务 shall 不发布该结果，并记录失败原因、失败阶段和可重试状态。
4.3 When 增强结果通过校验, the LLM 案例增强服务 shall 将其标记为 `valid`，可供下游向量索引、推荐展示和后台页面消费。
4.4 The LLM 案例增强服务 shall 保留每次生成所依据的案例更新时间和输出版本，支持审计和重新生成判断。
4.5 While 派生结果处于生成中或校验失败状态, the LLM 案例增强服务 shall 对下游返回明确状态，避免被误用为有效内容。
4.6 When 同一案例再次触发新的增强运行并通过校验准备写入新派生结果, the LLM 案例增强服务 shall 在写入新结果之前的同一持久化事务内删除该 `case_id` 的旧派生结果，保证同一 `case_id` 只有一条有效记录。

**下游消费约定（重要）**：下游消费方只消费 `status=valid` 的派生结果，不需要检查时间戳或过期标志。案例与派生结果的一致性由上游流程保证（案例修改后通过运营流程或管理后台显式触发重新增强）。本规格不实现自动过期检测或自动触发机制。

### Requirement 5: 推荐理由文案生成

**Objective:** As a 门店用户或督导, I want 相似案例推荐附带可解释文案, so that 我能理解推荐案例为什么值得参考以及应注意哪些差异。

#### Acceptance Criteria

5.1 When 检索推荐流程提供当前问题、候选案例和排序结果, the LLM 案例增强服务 shall 为每个候选案例生成推荐理由、可参考解决点和注意事项文案。
5.2 The LLM 案例增强服务 shall 在推荐文案中引用候选案例标识或可追溯来源，避免只返回黑盒结论。
5.3 If 候选案例信息不足以支持推荐理由, then the LLM 案例增强服务 shall 返回无法生成的原因而不是改变候选排序。
5.4 The LLM 案例增强服务 shall 不决定召回、过滤、相似度分值或最终排序。
5.5 Where 推荐文案生成失败, the LLM 案例增强服务 shall 返回失败状态（HTTP 503）。

### Requirement 6: 安全、隐私、失败处理与可观测性

**Objective:** As a 平台管理员, I want LLM 增强过程可控、可追踪且保护敏感内容, so that 门店和品牌案例数据不会因 AI 处理引入不可接受风险。

#### Acceptance Criteria

6.1 The LLM 案例增强服务 shall 在发送给外部模型前限制输入范围，只包含完成当前增强任务所需的案例内容。
6.2 The LLM 案例增强服务 shall 对提示词注入风险进行防护，避免案例正文中的指令改变系统输出格式或边界约束。
6.3 The LLM 案例增强服务 shall 记录 `model_id`、请求目的、结果状态和错误类型，供运维排查和审计；provider/base_url 仅作为运行时配置，不作为持久化字段。
6.4 If LLM 调用超时、限流或供应商失败, then the LLM 案例增强服务 shall 记录失败并支持受控重试，不阻塞案例基础查看和检索候选展示。
6.5 The LLM 案例增强服务 shall 明确供应商数据保留与隐私配置要求，缺少必要配置时不得启用生产增强流程。
