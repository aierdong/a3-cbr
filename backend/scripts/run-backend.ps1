#Requires -Version 5.1
<#
.SYNOPSIS
    启动 A3 案例管理后端（FastAPI + Uvicorn）。

.DESCRIPTION
    将工作目录切换到 backend 根目录后运行 uvicorn，确保加载 backend\.env。
    若 backend\.venv 不存在或不完整，将自动创建；否则自动激活该虚拟环境。
    每次启动前会在该虚拟环境中执行 ``pip install -e .``（不含 ``.[dev]``），以同步项目依赖。

.PARAMETER ListenHost
    监听地址，默认 0.0.0.0。

.PARAMETER Port
    监听端口，默认 8000。

.PARAMETER NoReload
    关闭热重载（适合与调试器配合或生产式本地运行）。

.EXAMPLE
    .\scripts\run-backend.ps1
.EXAMPLE
    .\scripts\run-backend.ps1 -ListenHost 127.0.0.1 -Port 8080 -NoReload
#>
param(
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $BackendRoot

$venvRoot = Join-Path $BackendRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$venvActivate = Join-Path $venvRoot "Scripts\Activate.ps1"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "未检测到可用虚拟环境（$venvPython），正在创建 .venv..." -ForegroundColor Yellow
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "未找到 python 命令。请安装 Python 3.11+ 并加入 PATH 后重试。"
    }
    & python -m venv $venvRoot
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "创建虚拟环境失败。若 .venv 目录已存在但不完整，请删除后重试。"
    }
    & $venvPython -m pip install --upgrade pip
}

if (Test-Path -LiteralPath $venvActivate) {
    Write-Host "激活虚拟环境: $venvActivate" -ForegroundColor Cyan
    . $venvActivate
}

Write-Host "同步项目依赖: pip install -e ." -ForegroundColor Cyan
& $venvPython -m pip install -e $BackendRoot

$uvicornArgs = @(
    "-m", "uvicorn",
    "app.main:app",
    "--host", $ListenHost,
    "--port", "$Port"
)
if (-not $NoReload) {
    $uvicornArgs += "--reload"
}

Write-Host "工作目录: $BackendRoot" -ForegroundColor Cyan
Write-Host "启动: python $($uvicornArgs -join ' ')" -ForegroundColor Cyan
& python @uvicornArgs
