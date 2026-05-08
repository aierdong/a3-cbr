# Consistency Check Rules

本文档定义 `kiro-validate-consistency` skill 的详细检查规则和模式。

## 需求编号格式规范

### 主需求格式
```markdown
### Requirement N: 需求标题
```
- `N` 为正整数（1, 2, 3, ...）
- 主需求不直接在任务中引用

### 子需求格式（验收标准）
```markdown
#### Acceptance Criteria

N.M When/If/While/Where 条件, the 系统 shall 动作...
```
- `N.M` 格式，其中 N 为主需求编号，M 为子需求序号
- 示例：1.1, 1.2, 2.1, 2.2, 3.1
- 这些是任务中 `_Requirements:` 引用的目标

### 提取模式
- 主需求：`^### Requirement [0-9]+:`
- 子需求：`^[0-9]+\.[0-9]+\s+(When|If|While|Where|The)`

## 组件命名约定

### 组件定义位置
1. **Components and Interfaces 章节**：
   ```markdown
   #### ComponentName
   ```
   - 组件名称使用 PascalCase（首字母大写驼峰）
   - 示例：CaseRouter, CaseService, CaseRepository

2. **组件表格**：
   ```markdown
   | Component | Domain/Layer | Intent | Req Coverage | ... |
   |-----------|--------------|--------|--------------|-----|
   | CaseRouter | API/HTTP | ... | ... | ... |
   ```

3. **Architecture Pattern & Boundary Map**：
   - Mermaid 图或文本描述中的组件名称

### 提取模式
- 标题形式：`^#### [A-Z][a-zA-Z0-9]+$`
- 表格形式：`^\| ([A-Z][a-zA-Z0-9]+) \|`
- 边界注解：`_Boundary: ([A-Z][a-zA-Z0-9]+)_`

## 任务引用格式

### Requirements 引用
```markdown
- [ ] 2.1 任务描述
  - 详细说明...
  - _Requirements: 1.1, 1.3, 2.2, 3.4_
```
- 格式：`_Requirements: N.M, N.M, ..._`
- 多个需求用逗号分隔
- 需求编号必须存在于 requirements.md 中

### Boundary 引用
```markdown
- [ ] 2.1 任务描述
  - 详细说明...
  - _Boundary: ComponentName_
```
- 格式：`_Boundary: ComponentName_`
- 组件名称必须存在于 design.md 中
- 每个任务通常只有一个 Boundary

### Depends 引用（可选）
```markdown
- [ ] 2.3 任务描述
  - 详细说明...
  - _Depends: 2.1, 2.2_
```
- 格式：`_Depends: N.M, N.M, ..._`
- 表示任务依赖关系
- 不在本 skill 的验证范围内

### 提取模式
- Requirements：`_Requirements:\s*([0-9]+\.[0-9]+(?:,\s*[0-9]+\.[0-9]+)*)_`
- Boundary：`_Boundary:\s*([A-Z][a-zA-Z0-9]+)_`

## Revalidation Triggers 格式

### 触发条件位置
```markdown
### Revalidation Triggers

- 触发条件 1
- 触发条件 2
- 触发条件 3
```

### 触发条件类型与对应任务

#### 1. 文档更新触发
**关键词**：
- "须同步修订" / "must update" / "must revise"
- "修订契约文档" / "update contract document"
- "同步更新" / "synchronize"

**对应任务特征**：
- 任务描述包含：文档、契约、contract、doc、更新、修订
- 示例：`- [ ] 3.5 更新 contract-a3-case-detail-for-enrichment.md 契约文档`

#### 2. 测试验证触发
**关键词**：
- "运行集成测试" / "run integration tests"
- "验证兼容性" / "verify compatibility"
- "触发下游重新校验" / "trigger downstream revalidation"

**对应任务特征**：
- 任务描述包含：测试、test、验证、校验、兼容性
- 示例：`- [ ] 4.3 运行集成测试验证 llm-case-enrichment 兼容性`

#### 3. Schema/模型变更触发
**关键词**：
- "字段名称、类型、必填规则" / "field name, type, required rules"
- "枚举值" / "enum values"
- "响应结构" / "response structure"

**对应任务特征**：
- 任务描述包含：schema、model、字段、枚举、结构
- 示例：`- [ ] 2.1 定义案例请求、响应和分页契约`

#### 4. API 契约变更触发
**关键词**：
- "API 路径" / "API path"
- "响应结构" / "response structure"
- "错误结构" / "error structure"

**对应任务特征**：
- 任务描述包含：API、接口、路径、响应、错误
- 示例：`- [ ] 3.1 实现创建、编辑与删除接口`

### 提取模式
- 章节标题：`^### Revalidation Triggers$`
- 触发条件：`^-\s+(.+)$`（在 Revalidation Triggers 章节内）

## 边界情况处理

### 空文档
- **空 requirements.md**：警告但继续，跳过需求覆盖检查
- **空 design.md**：警告但继续，跳过组件实现检查
- **空 tasks.md**：错误，无法验证，停止

### 格式错误
- **需求编号格式错误**：记录警告，跳过该需求
- **组件名称不符合约定**：记录警告，跳过该组件
- **任务引用格式错误**：记录错误，标注具体行号

### 缺失章节
- **无 Acceptance Criteria**：警告，使用主需求编号（N）作为备选
- **无 Components and Interfaces**：警告，尝试从表格提取
- **无 Revalidation Triggers**：跳过该检查，不报错

### 多语言支持
- **中文文档**：支持中文关键词（须同步修订、运行集成测试等）
- **英文文档**：支持英文关键词（must update, run integration tests等）
- **混合文档**：同时支持中英文关键词

## 验证严格度

### 必须通过的检查（FAIL 条件）
1. 存在未覆盖的需求（requirements without tasks）
2. 存在断裂的需求引用（tasks reference non-existent requirements）
3. 存在断裂的组件引用（tasks reference non-existent components）

### 警告级别的检查（不影响 PASS）
1. 未实现的组件（components without tasks）- 可能是抽象组件或接口
2. 孤立任务（tasks without requirements）- 可能是基础设施任务
3. 未覆盖的 Revalidation Triggers - 可能由多个任务共同覆盖

### 容忍度
- **组件覆盖**：抽象组件、接口、工具类可能没有直接实现任务
- **Trigger 覆盖**：一个 trigger 可能由多个任务共同覆盖，不要求精确 1:1 映射
- **语义理解**：基于关键词和上下文判断，不要求完全匹配

## 报告优先级

### 高优先级问题（必须修复）
1. 断裂的需求引用
2. 断裂的组件引用
3. 未覆盖的核心需求

### 中优先级问题（建议修复）
1. 孤立任务
2. 未实现的核心组件
3. 未覆盖的关键 Revalidation Triggers

### 低优先级问题（可选修复）
1. 未实现的工具类组件
2. 未覆盖的次要 Revalidation Triggers

## 示例

### 正确的引用
```markdown
# requirements.md
### Requirement 1: 案例创建
1.1 When 用户提交案例, the 系统 shall 保存案例
1.2 The 系统 shall 返回案例标识

# design.md
#### CaseService
负责案例业务逻辑

# tasks.md
- [ ] 2.1 实现案例创建服务
  - _Requirements: 1.1, 1.2_
  - _Boundary: CaseService_
```

### 错误的引用
```markdown
# tasks.md
- [ ] 2.1 实现案例创建服务
  - _Requirements: 1.1, 5.7_  # 5.7 不存在
  - _Boundary: FooService_    # FooService 不存在
```

### Revalidation Trigger 覆盖示例
```markdown
# design.md
### Revalidation Triggers
- `CaseDetailResponse` 的字段变更时，须同步修订 `docs/contract-a3-case-detail-for-enrichment.md`

# tasks.md（正确覆盖）
- [ ] 2.1 定义案例请求、响应和分页契约
  - 定义 CaseDetailResponse...
  - _Requirements: 1.1, 5.1_
  - _Boundary: CaseSchemas_

- [ ] 3.5 更新下游契约文档
  - 同步更新 docs/contract-a3-case-detail-for-enrichment.md
  - _Requirements: 7.1_
  - _Boundary: Documentation_
```
