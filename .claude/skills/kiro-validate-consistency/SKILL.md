---
name: kiro-validate-consistency
description: Check consistency between tasks.md, design.md, and requirements.md to ensure complete traceability and coverage.
allowed-tools: Read, Grep, Glob
argument-hint: <feature-name>
metadata:
  shared-rules: "consistency-check.md"
---

# kiro-validate-consistency Skill

## Role
You are a specialized skill for conducting consistency validation of spec documents to ensure complete traceability and coverage between requirements, design, and tasks.

## Core Mission
- **Mission**: Verify bidirectional traceability and complete coverage across spec documents (requirements.md, design.md, tasks.md)
- **Success Criteria**:
  - All requirements have corresponding task coverage
  - All design components and boundary elements have implementation tasks
  - All task references point to existing requirements and boundary elements (in Components table OR File Structure Plan)
  - No orphaned tasks without requirement traceability
  - All implementation-type Revalidation Triggers have corresponding tasks; all external-change-type triggers have boundary constraints
  - Clear, actionable report of any inconsistencies found

## Execution Steps

### Step 1: Gather Context

If spec context is already available from conversation, skip redundant file reads.
Otherwise, load all necessary context:
- Read `.kiro/specs/{feature}/spec.json` for metadata and language
- Read `.kiro/specs/{feature}/requirements.md`
- Read `.kiro/specs/{feature}/design.md`
- Read `.kiro/specs/{feature}/tasks.md`

### Step 2: Extract Traceability Data

**Extract Requirement IDs** (from requirements.md):
- Pattern: `### Requirement N:` for main requirements
- Pattern: `N.M` format in Acceptance Criteria sections (e.g., 1.1, 1.2, 2.1)
- Use Grep to find all requirement IDs
- Build set: `{1.1, 1.2, 1.3, 2.1, 2.2, ...}`

**Extract Component Names and Boundary Elements** (from design.md):
- Pattern: `#### ComponentName` in Components and Interfaces section
- Also check Architecture Pattern & Boundary Map for component names
- Look for component tables with "Component" column
- Build set of components: `{CaseRouter, CaseService, CaseRepository, ...}`
- **Also extract boundary elements from File Structure Plan**:
  - Pages (e.g., `CaseListPage.vue`, `RecommendationPage.vue`)
  - Composables (e.g., `useCases.ts`, `useRecommendations.ts`)
  - Common components (e.g., `LoadingState.vue`, `ErrorNotice.vue`)
  - Files and directories (e.g., `main.ts`, `router/`, `api/generated/`)
  - Test boundaries (e.g., `component tests`, `integration tests`)
- Build combined set: `{components + pages + composables + files + test boundaries}`

**Extract Task References** (from tasks.md):
- Pattern: `_Requirements: X.X, Y.Y_` for requirement references
- Pattern: `_Boundary: ComponentName_` for component boundaries
- Parse each task to extract:
  - Task ID (e.g., 2.1, 2.2)
  - Referenced requirement IDs
  - Referenced component names
- Build mappings: `task_to_reqs`, `task_to_components`

**Extract Revalidation Triggers** (from design.md):
- Find "Revalidation Triggers" or "Revalidation Triggers" section
- Extract all trigger conditions (bullet points)
- Identify triggers that imply implementation actions:
  - "须同步修订" / "must update" → doc update tasks
  - "运行集成测试" / "run integration tests" → test tasks
  - "触发下游重新校验" / "trigger downstream revalidation" → schema/test tasks
  - "提供" / "provide" → implementation tasks

### Step 3: Run Consistency Checks

**Check 1: Requirements Coverage**
- For each requirement ID in requirements.md:
  - Search tasks.md for `_Requirements:` annotations containing this ID
  - If not found: Mark as "uncovered requirement"
- Report: List of requirements without any task coverage

**Check 2: Component Implementation**
- For each component in design.md Components section:
  - Search tasks.md for `_Boundary:` annotations containing this component
  - If not found: Mark as "unimplemented component"
- Report: List of components without any implementation task

**Check 3: Task Reference Validity (Requirements)**
- For each requirement ID referenced in tasks.md `_Requirements:`:
  - Verify it exists in requirements.md
  - If not found: Mark as "broken requirement reference"
- Report: List of tasks with invalid requirement references

**Check 4: Task Reference Validity (Boundary Elements)**
- **Validation Rule**: `_Boundary:` field contains a broader scope than just components from the Components table. It includes: components, pages, composables, files, directories, and test boundaries.
- For each boundary element referenced in tasks.md `_Boundary:`:
  - First, check if it exists in design.md Components and Interfaces table
  - If not found in Components table, check if it exists in File Structure Plan section
  - If not found in either location: Mark as "broken boundary reference"
- Report: List of tasks with invalid boundary references (not found in Components table OR File Structure Plan)

**Check 5: Orphaned Tasks**
- For each task in tasks.md:
  - **Only check sub-tasks** (tasks with format `X.Y`, e.g., 1.1, 2.3, 5.2)
  - **Skip parent tasks** (tasks with format `X.`, e.g., 1., 2., 3.) as they are organizational headers
  - Check if the sub-task has `_Requirements:` annotation
  - If missing: Mark as "orphaned task"
- Report: List of sub-tasks without requirement traceability

**Check 6: Revalidation Triggers Coverage**
- **Validation Rule**: Revalidation Triggers are classified into two types:
  1. **Implementation-type triggers**: Require corresponding implementation tasks in the current spec (e.g., contract sync mechanisms, test tasks, schema validation)
  2. **External-change-type triggers**: Describe future external changes that trigger re-validation. Current spec addresses these through boundary constraints (requirements, design decisions), NOT through implementation tasks.
  
- For each trigger in design.md Revalidation Triggers section:
  - **Step 1: Classify the trigger type**:
    - Implementation-type indicators: "须同步修订" / "must update", "运行集成测试" / "run integration tests", "触发下游重新校验" / "trigger downstream revalidation", "提供" / "provide"
    - External-change-type indicators: "产品要求新增" / "product requires new", "技术栈迁移" / "technology stack migration", "从...迁移到" / "migrate from...to"
  
  - **Step 2: Verify coverage based on type**:
    - **For implementation-type triggers**: Search tasks.md for tasks that address this trigger:
      - Doc update triggers → look for tasks mentioning doc/contract/契约文档
      - Test triggers → look for tasks mentioning test/测试/验证
      - Schema triggers → look for tasks mentioning schema/model/契约
      - If no matching task found: Mark as "uncovered trigger"
    
    - **For external-change-type triggers**: Verify boundary constraints exist:
      - Check if requirements.md or design.md explicitly define boundary constraints that address this trigger
      - Check if design.md explains the current approach/technology choice
      - These triggers do NOT require implementation tasks; they describe scenarios that would require a separate spec revision
      - Mark as "covered by boundary constraints" if constraints exist
  
- Report: List of triggers by type, with coverage status and explanation

### Step 4: Generate Report

Generate a comprehensive report in the language specified in spec.json:

```markdown
## 一致性验证报告

**功能**: {feature-name}
**状态**: PASS | FAIL
**检查时间**: {timestamp}

### 摘要
- 需求总数: X
- 设计组件总数: Y（Components 表中定义的关键组件）
- 设计边界总数: Z（包含 Components 表 + File Structure Plan 中定义的页面、composables、文件等）
- 任务总数: N
- Revalidation Triggers 总数: M
- 发现问题: P

### 需求覆盖度
✓ 已覆盖: [需求编号列表]
✗ 缺失覆盖: [需求编号列表]

### 组件与边界实现度

**验证规则说明**: `_Boundary:` 字段包含的边界范围广于 Components 表，包括：关键组件、页面、composables、文件、目录、测试边界等。验证时检查 Boundary 引用是否在 design.md 的 Components 表或 File Structure Plan 中有定义。

✓ 已实现的关键组件（来自 Components 表）: [组件列表]
✓ 已定义的其他边界元素（来自 File Structure Plan）: [页面、composables、文件等列表]
✗ 未实现: [组件或边界元素列表]

### 任务引用有效性
✓ 有效引用: X 个任务
✗ 断裂引用:
  - 任务 2.3 引用不存在的需求 5.7
  - 任务 3.1 引用不存在的组件 "FooService"

### 孤立任务
✗ 缺少需求可追溯性的任务:
  - 任务 4.2: 无 _Requirements: 注解

### Revalidation Triggers 覆盖度（语义核对）

**验证规则说明**: Revalidation Triggers 分为两类：
1. **实施类触发条件**: 需要当前规格实现对应任务（如契约同步机制、测试任务）
2. **外部变化类触发条件**: 描述未来可能发生的外部变化，当前规格通过边界约束应对，不需要对应实施任务

**已识别的 Revalidation Triggers**:

✓ **Trigger N（实施类）**: [触发条件描述]
**覆盖方式**: 实施任务
  - 任务 X.Y: [任务描述]（需求 A.B, C.D）

✓ **Trigger M（外部变化类）**: [触发条件描述]
**覆盖方式**: 边界约束（不需要对应实施任务）
  - 需求 X.Y: [边界约束描述]
  - design.md § [章节]: [设计决策说明]
  - **说明**: 此触发条件描述 [场景类型]，当前规格已明确 [边界约束内容]。若触发此条件，需单独立项 [应对措施]。

✗ **缺失覆盖的触发条件**:
  - "须同步修订 contract-a3-case-detail-for-enrichment.md" → 未找到对应的文档更新任务
  - "运行集成测试验证 llm-case-enrichment 兼容性" → 未找到对应的集成测试任务

### 建议
1. 为以下需求添加任务: [列表]
2. 为以下组件添加任务: [列表]
3. 修复任务中的断裂引用: [列表]
4. 为孤立任务添加 _Requirements: 注解
5. 为以下 Revalidation Triggers 添加对应任务: [列表]

### 决策
- **PASS**: 所有一致性检查通过
- **FAIL**: 发现 M 个问题，见上述建议
```

## Important Constraints

- **Context Efficiency**: Skip redundant file reads if spec documents are already loaded in conversation
- **Language Consistency**: Use language from spec.json for all output
- **Actionable Feedback**: All findings must be specific and actionable
- **Balanced Assessment**: Report both successes and issues
- **Boundary Scope Understanding**: `_Boundary:` field includes components, pages, composables, files, directories, and test boundaries. Verify against both Components table AND File Structure Plan.
- **Trigger Type Classification**: Distinguish between implementation-type triggers (require tasks) and external-change-type triggers (require boundary constraints, not tasks)
- **Semantic Understanding**: For Revalidation Triggers, understand implied actions and classify trigger type before checking coverage
- **Tolerance for Reasonable Coverage**: A trigger may be covered by multiple tasks collectively; don't require exact 1:1 mapping

## Tool Guidance

- **Read**: Load spec documents (spec.json, requirements.md, design.md, tasks.md)
- **Grep**: Extract requirement IDs, component names, task references, and triggers
- **Pattern Matching**: Use regex patterns to identify structured annotations

## Output Description

Provide output in the language specified in spec.json with:

1. **Report Header**: Feature name, status (PASS/FAIL), timestamp
2. **Summary**: Counts of requirements, components, tasks, triggers, and issues
3. **Coverage Sections**: Requirements, components, task references, orphaned tasks, triggers
4. **Recommendations**: Specific actions to resolve each issue
5. **Final Decision**: PASS or FAIL with rationale

**Format Requirements**:
- Use Markdown headings for clarity
- Use ✓ for passed checks, ✗ for failed checks
- Keep recommendations concise and actionable
- Group related issues together

## Safety & Fallback

### Error Scenarios

- **Missing Files**: 
  - If requirements.md missing: "无法验证 - requirements.md 不存在"
  - If design.md missing: "无法验证 - design.md 不存在"
  - If tasks.md missing: "无法验证 - tasks.md 不存在"
  - Stop validation and report which files are missing

- **Empty Sections**:
  - If no requirements found: Warning but continue with other checks
  - If no components found: Warning but continue with other checks
  - If no tasks found: "无法验证 - tasks.md 为空"

- **Malformed References**:
  - If `_Requirements:` has invalid format: Report parsing error with line context
  - If `_Boundary:` has invalid format: Report parsing error with line context
  - Continue validation with available data

- **Language Undefined**: Default to Simplified Chinese (`zh-CN`) if spec.json doesn't specify language

### Next Phase: Implementation

**If Consistency Validation Passes (PASS Decision)**:
- Proceed to implementation: `/kiro-impl {feature}`
- Or run additional validation: `/kiro-validate-impl {feature}` after implementation

**If Consistency Issues Found (FAIL Decision)**:
- Address critical issues identified in report
- Update requirements.md, design.md, or tasks.md as needed
- Re-run `/kiro-validate-consistency {feature}` to verify fixes

**Note**: Consistency validation is recommended after task generation and before implementation. It catches spec-level issues early and ensures all design commitments are tracked in tasks.
