# Alembic Migration Guidelines

updated_at: 2026-05-11

## JSON Column Type

所有 JSON 类型应使用 PostgreSQL 的 `jsonb` 类型代替。

### 导入语句

```python
from sqlalchemy.dialects import postgresql
```

### 列定义

使用 `with_variant` 变体定义，确保跨数据库兼容性：

```python
# 正确写法
sa.JSON().with_variant(postgresql.JSONB, "postgresql")

# 错误写法
sa.JSON().with_variant(sa.JSON(), "postgresql")
# 同样错误
sa.JSON()
```

### 示例

```python
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# 定义 JSONB 列
applied_filters = sa.Column(
    sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
    nullable=False
)
```

---

_本文件沉淀 Alembic 数据迁移的通用规范，确保跨环境的数据库 schema 变更一致性。_
