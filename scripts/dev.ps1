#Requires -Version 5.1
<#
. 装修企业 AI Agent Workbench —— 本地开发任务运行器
. -----------------------------------------------------------------------------
. 本机未安装 make，因此使用 PowerShell 任务运行器承载 README 中的命令。
. 用法:  ./scripts/dev.ps1 <task>
. 可用:  help | bootstrap | install | up | down | status | logs | api
.        test | cov |lint | fmt | typecheck | check
.        fe-install | fe-dev | fe-build | fe-test
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        'help', 'bootstrap', 'install',
        'up', 'down', 'status', 'logs', 'api',
        'test', 'cov', 'lint', 'fmt', 'typecheck', 'check',
        'migrate', 'revision', 'seed',
        'fe-install', 'fe-dev', 'fe-build', 'fe-test'
    )]
    [string]$Task = 'help'
    # 仅 revision 任务使用：./scripts/dev.ps1 revision "migration message"
    [Parameter(Position = 1)]
    [string]$Message = 'auto revision'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$WebDir = Join-Path $Root 'apps\web'

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "step '$Name' failed with exit code $LASTEXITCODE" }
}

function Assert-Venv {
    if (-not (Test-Path $VenvPython)) {
        throw "未找到虚拟环境 $VenvPython，请先执行: ./scripts/dev.ps1 bootstrap"
    }
}

switch ($Task) {
    'help' {
        Write-Host @"

装修企业 AI Agent Workbench - 本地任务运行器

  基础设施   bootstrap  创建 .venv 并安装全部依赖
             up         启动 Postgres / Redis / Kafka
             down       停止并移除容器（保留 volume）
             status     查看容器与健康状态
             logs       跟踪容器日志

  后端       install    重新以 editable 方式安装所有本地包
             api        启动 FastAPI (http://127.0.0.1:8000)
             migrate    执行 alembic upgrade head
             revision   自动生成迁移 <message>
             seed       灌入演示数据
             test       运行全部测试
             cov        运行测试并输出覆盖率
             lint       ruff check
             fmt        ruff format
             typecheck  mypy
             check      lint + typecheck + test

  前端       fe-install npm install
             fe-dev     vite dev server
             fe-build   vue-tsc 类型检查 + vite build
             fe-test    vitest run

"@
    }

    'bootstrap' {
        if (-not (Test-Path $VenvPython)) {
            Invoke-Step '创建虚拟环境' { py -m venv (Join-Path $Root '.venv') }
        }
        Invoke-Step '安装后端依赖（含本地包 editable）' {
            & $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements-dev.txt')
        }
        Write-Host "`n完成。执行 ./scripts/dev.ps1 up 启动基础设施。" -ForegroundColor Green
    }

    'install' {
        Assert-Venv
        Invoke-Step '安装后端依赖' {
            & $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements-dev.txt')
        }
    }

    'up' {
        Invoke-Step '启动基础设施' { Push-Location $Root; docker compose up -d; Pop-Location }
    }

    'down' {
        Invoke-Step '停止基础设施' { Push-Location $Root; docker compose down; Pop-Location }
    }

    'status' {
        Invoke-Step '容器状态' { Push-Location $Root; docker compose ps; Pop-Location }
    }

    'logs' {
        Push-Location $Root
        docker compose logs -f
        Pop-Location
    }

    'api' {
        Assert-Venv
        Push-Location $Root
        try {
            $env:PYTHONPATH = "apps/api/src;packages/schemas/src;packages/infrastructure/src"
            & $VenvPython -m uvicorn dw_api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
        }
        finally { Pop-Location }
    }

    'test' {
        Assert-Venv
        Invoke-Step 'pytest' { & $VenvPython -m pytest }
    }

    'cov' {
        Assert-Venv
        Invoke-Step 'pytest --cov' {
            & $VenvPython -m pytest --cov=dw_api --cov=dw_schemas --cov=dw_infrastructure --cov-report=term-missing
        }
    }

    'lint' {
        Assert-Venv
        Invoke-Step 'ruff check' { & $VenvPython -m ruff check . }
    }

    'fmt' {
        Assert-Venv
        Invoke-Step 'ruff format' { & $VenvPython -m ruff format . }
    }

    'typecheck' {
        Assert-Venv
        Invoke-Step 'mypy' { & $VenvPython -m mypy apps packages }
    }

    'migrate' {
        Assert-Venv
        Invoke-Step 'alembic upgrade head' { & $VenvPython -m alembic upgrade head }
    }

    'revision' {
        Assert-Venv
        Invoke-Step 'alembic revision --autogenerate' {
            & $VenvPython -m alembic revision --autogenerate -m $Message
        }
    }

    'seed' {
        Assert-Venv
        Invoke-Step 'seed demo data' { & $VenvPython scripts/seed.py }
    }

    'check' {
        Assert-Venv
        Invoke-Step 'ruff check' { & $VenvPython -m ruff check . }
        Invoke-Step 'mypy' { & $VenvPython -m mypy apps packages }
        Invoke-Step 'pytest' { & $VenvPython -m pytest }
    }

    'fe-install' {
        Invoke-Step 'npm install' { Push-Location $WebDir; npm install; Pop-Location }
    }

    'fe-dev' {
        Invoke-Step 'vite dev' { Push-Location $WebDir; npm run dev; Pop-Location }
    }

    'fe-build' {
        Invoke-Step 'vue-tsc + vite build' { Push-Location $WebDir; npm run build; Pop-Location }
    }

    'fe-test' {
        Invoke-Step 'vitest' { Push-Location $WebDir; npm run test; Pop-Location }
    }
}
