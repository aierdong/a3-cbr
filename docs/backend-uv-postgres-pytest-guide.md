# Backend 测试环境完整清单（uv + PostgreSQL + pytest）

本文档用于在 Windows（PowerShell）环境下，完成 `backend` 项目的测试环境搭建与执行，重点覆盖仓储层测试依赖的 PostgreSQL 外部环境。

## 1. 前置条件

- 已安装 Python（建议 3.11+）
- 已安装 Git
- 可用的终端：PowerShell
- 项目路径：`E:\git\cbr-a3`

## 2. 安装与使用 uv（推荐）

如果尚未安装 `uv`，先执行：

```powershell
pip install uv
```

进入后端目录并创建虚拟环境：

```powershell
cd E:\git\cbr-a3\backend
uv venv
.\.venv\Scripts\Activate.ps1
```

安装项目依赖（含测试依赖）：

```powershell
uv pip install -e .[dev]
```

验证当前解释器是否为虚拟环境：

```powershell
where python
```

## 3. 准备 PostgreSQL 外部环境

仓储测试默认依赖数据库连接（来自 `app/core/config.py`）：

- `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/a3_cases`
- `DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@localhost:5432/a3_cases`
- `ALEMBIC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/a3_cases`

你可以使用以下两种方式准备数据库。

### 3.1 方式 A：Docker（最快）

启动 PostgreSQL 容器：

```powershell
docker run --name a3-test-pg `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=a3_cases `
  -p 5432:5432 `
  -d postgres:16
```

检查数据库就绪：

```powershell
docker logs a3-test-pg
```

出现 `database system is ready to accept connections` 后即可运行测试。

停止与删除容器（可选）：

```powershell
docker stop a3-test-pg
docker rm a3-test-pg
```

### 3.2 方式 B：本机 PostgreSQL 服务

确保以下条件成立：

- PostgreSQL 正在运行并监听 `localhost:5432`
- 存在数据库 `a3_cases`
- 连接用户和密码可用（默认示例为 `postgres/postgres`）

若需创建数据库，可在 `psql` 中执行：

```sql
CREATE DATABASE a3_cases;
```

## 4. 使用 .env 覆盖数据库连接（推荐）

如果你不使用默认账号密码，请在 `backend` 目录创建 `.env` 文件：

```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/<db_name>
DATABASE_URL_SYNC=postgresql+psycopg2://<user>:<password>@localhost:5432/<db_name>
ALEMBIC_DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<db_name>
```

说明：

- 项目配置会自动读取 `backend/.env`
- 修改后重新执行测试即可生效

## 5. 运行 pytest（完整清单）

进入并激活虚拟环境（每次新开终端都要激活一次）：

```powershell
cd E:\git\cbr-a3\backend
.\.venv\Scripts\Activate.ps1
```

运行仓储测试（用于验证 33 项数据库相关测试）：

```powershell
pytest tests/cases/test_case_repository.py -q
```

运行全部测试：

```powershell
pytest -q
```

按关键字筛选（示例）：

```powershell
pytest -k repository -q
```

## 6. 常见问题排查

### 6.1 `connection refused` / `could not connect`

原因：PostgreSQL 未启动、端口不对、用户名密码错误。  
处理：

- 确认 `localhost:5432` 可连通
- 检查 `.env` 连接串
- 确认 Docker 容器或本机服务状态

### 6.2 `password authentication failed`

原因：账号密码不匹配。  
处理：

- 修正 `.env` 中账号密码
- 或将数据库用户密码改为与连接串一致

### 6.3 只有 repository 测试报错，其他测试通过

原因：仓储层测试依赖真实 PostgreSQL；校验/服务层测试不一定依赖。  
处理：按本文第 3 节准备数据库环境后重跑。

### 6.4 PowerShell 无法执行激活脚本

可临时放宽执行策略（当前用户）：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 7. 一次性快速流程（复制即用）

```powershell
cd E:\git\cbr-a3\backend
pip install uv
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e .[dev]
docker run --name a3-test-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=a3_cases -p 5432:5432 -d postgres:16
pytest tests/cases/test_case_repository.py -q
pytest -q
```

如果最后仍有失败，请优先贴出首个失败堆栈（含异常类型和报错行），再继续定位实现问题或环境问题。
