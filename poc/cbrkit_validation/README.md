# CBRKit 集成验证 PoC

## 目的

在实施 `cbr-retrieval-recommendation` 规格之前，验证 CBRKit 是否满足设计文档中的核心假设。

## 验证目标

1. **候选集内聚合**: CBRKit 是否支持仅对预先筛选的候选集进行聚合，而不触发全量 casebase 检索
2. **对象隔离**: CBRKit 内部对象是否可以隔离，不泄漏到数据库或 API 响应
3. **归一化位置**: 确认归一化和重加权逻辑应在适配层实现
4. **加权聚合 API**: 验证 CBRKit 的实际加权聚合 API 形式

## 执行步骤

### 1. 安装依赖

```bash
cd poc/cbrkit_validation
pip install -r requirements.txt
```

### 2. 运行验证脚本

```bash
python test_cbrkit_integration.py
```

### 3. 查看验证报告

脚本会输出详细的验证报告，包括：
- 每个验证项的通过/失败状态
- CBRKit 可用的类和方法
- 实际 API 模式示例
- 适配层实施建议

## 预期结果

### 成功场景

如果所有验证通过，输出应包含：
- ✓ CBRKit 支持候选集内聚合
- ✓ 可以提取 case.id 和 case.features
- ✓ 归一化应在适配层实现
- ✓ 找到加权聚合 API（weighted_sum 或类似方法）

**下一步**: 根据验证结果更新 `design.md` 中的 CBRKit 集成代码，继续实施。

### 失败场景

如果验证失败，可能的原因：
1. **CBRKit 未安装**: 运行 `pip install cbrkit`
2. **API 不匹配**: CBRKit 实际 API 与设计假设不符
3. **版本问题**: CBRKit 版本过旧或过新

**下一步**: 
- 查阅 CBRKit 官方文档: https://github.com/wi2trier/cbrkit
- 根据实际 API 更新设计文档
- 如果 CBRKit 不满足需求，考虑替代方案

## 替代方案（如果 CBRKit 验证失败）

1. **自行实现加权聚合**:
   ```python
   def aggregate_scores(candidates, weights):
       for candidate in candidates:
           final_score = (
               weights['vector'] * candidate.vector_score +
               weights['semantic'] * candidate.semantic_score +
               weights['structured'] * candidate.structured_score +
               weights['business'] * candidate.business_score
           )
           candidate.final_score = final_score
       return sorted(candidates, key=lambda c: c.final_score, reverse=True)
   ```

2. **使用其他 CBR 框架**: 评估 PyCBR、myCBR 等替代方案

3. **简化为规则排序**: 如果 CBR 框架都不满足需求，使用基于规则的多维度排序

## 关键决策点

根据验证结果，需要在设计文档中明确：

1. **CBRKit 集成方式**: 使用实际验证通过的 API 模式
2. **适配层职责**: 明确归一化、重加权、对象映射的实施位置
3. **降级策略**: 如果 CBRKit 调用失败，如何降级排序

## 输出

验证完成后，应更新以下文档：

1. `.kiro/specs/cbr-retrieval-recommendation/design.md`
   - 更新 `CBROrchestrator` 章节的集成代码
   - 移除"待实施时验证"的不确定性表述
   - 补充实际验证通过的 API 模式

2. `.kiro/specs/cbr-retrieval-recommendation/research.md`
   - 记录 CBRKit 验证过程和结果
   - 保存 API 探索记录供后续参考

3. `.kiro/specs/cbr-retrieval-recommendation/tasks.md`
   - 将"CBRKit API 验证"任务标记为已完成
   - 根据验证结果调整后续实施任务的优先级
