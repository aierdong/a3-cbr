#Requires -Version 5.1
<#
.SYNOPSIS
    在 backend 根目录下执行 Alembic 数据库迁移。

.DESCRIPTION
    使用 app.core.config.settings 中的 alembic_database_url（与 alembic\env.py 一致）。
    若 backend\.venv 不存在或不完整，将自动创建并 pip install -e .；否则自动激活该虚拟环境。
    需已配置 backend\.env 或环境变量，且 PostgreSQL 可访问。

.PARAMETER Operation
    upgrade  — 升级到指定版本（默认 Revision=head）
    downgrade — 回退到指定版本（未指定 Revision 时默认为 -1，即上一版本）
    current  — 显示当前数据库版本
    history  — 显示迁移历史
    heads    — 显示多个 head（分支合并前排查用）

.PARAMETER Revision
    upgrade / downgrade 的目标版本，例如 head、base、004_xxx 或 -1。

.EXAMPLE
    .\scripts\migrate-db.ps1
.EXAMPLE
    .\scripts\migrate-db.ps1 -Operation downgrade -Revision -1
.EXAMPLE
    .\scripts\migrate-db.ps1 -Operation current
#>
param(
    [ValidateSet("upgrade", "downgrade", "current", "history", "heads")]
    [string]$Operation = "upgrade",
    [string]$Revision = ""
)

$ErrorActionPreference = "Stop"

$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $BackendRoot

$venvRoot = Join-Path $BackendRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$venvAlembic = Join-Path $venvRoot "Scripts\alembic.exe"
$venvActivate = Join-Path $venvRoot "Scripts\Activate.ps1"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "未检测到可用虚拟环境（$venvPython），正在创建 .venv 并安装依赖..." -ForegroundColor Yellow
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "未找到 python 命令。请安装 Python 3.11+ 并加入 PATH 后重试。"
    }
    & python -m venv $venvRoot
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "创建虚拟环境失败。若 .venv 目录已存在但不完整，请删除后重试。"
    }
    Write-Host "同步项目依赖: pip install -e ." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e $BackendRoot
}

if (Test-Path -LiteralPath $venvActivate) {
    Write-Host "激活虚拟环境: $venvActivate" -ForegroundColor Cyan
    . $venvActivate
}

switch ($Operation) {
    "upgrade" {
        if (-not $Revision) { $Revision = "head" }
        Write-Host "执行: alembic upgrade $Revision" -ForegroundColor Cyan
        & $venvAlembic upgrade $Revision
    }
    "downgrade" {
        if (-not $Revision) { $Revision = "-1" }
        Write-Host "执行: alembic downgrade $Revision" -ForegroundColor Cyan
        & $venvAlembic downgrade $Revision
    }
    "current" {
        Write-Host "执行: alembic current" -ForegroundColor Cyan
        & $venvAlembic current
    }
    "history" {
        Write-Host "执行: alembic history" -ForegroundColor Cyan
        & $venvAlembic history
    }
    "heads" {
        Write-Host "执行: alembic heads" -ForegroundColor Cyan
        & $venvAlembic heads
    }
}
