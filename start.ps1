# Gitter Startup Script (PowerShell)
# Starts FastAPI Backend (8000) + Next.js Frontend (3000)
# 支持换机自动修复：venv 重建、依赖重装、镜像回退、版本校验

$LOGFILE = "$PSScriptRoot\start.log"
$MIN_PYTHON = "3.9"
$MIN_NODE = "20.9.0"

function Write-Log {
    param([string]$Message)
    "$(Get-Date) $Message" | Out-File -FilePath $LOGFILE -Append -Encoding UTF8
}

function Exit-WithError {
    param([string]$Message)
    Write-Host "[Error] $Message" -ForegroundColor Red
    Write-Log "ERROR: $Message"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Log "Starting Gitter"

Write-Host "============================================"
Write-Host "  Gitter Startup"
Write-Host "  FastAPI Backend (8000) + Next.js Frontend (3000)"
Write-Host "============================================"
Write-Host ""

Set-Location $PSScriptRoot
Write-Log "Current directory: $(Get-Location)"

# ============================================================
# 辅助函数：解析并比较版本号
# ============================================================
function Compare-Version {
    param([string]$Actual, [string]$Required)
    $a = [Version]($Actual -replace '^[a-zA-Z]+', '' -replace '^v', '')
    $r = [Version]($Required -replace '^[a-zA-Z]+', '' -replace '^v', '')
    return $a.CompareTo($r)
}

# ============================================================
# 步骤1：检查 Python 环境（版本校验 + 可执行性）
# ============================================================
Write-Host "[Check] Python environment..."
try {
    $pyVersionRaw = python --version 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Python not found" }
    $pyVersion = ($pyVersionRaw -replace 'Python\s*', '').Trim()
    Write-Host "[OK] Python version: $pyVersionRaw"
    Write-Log "Python check passed: $pyVersion"

    if ((Compare-Version $pyVersion $MIN_PYTHON) -lt 0) {
        Exit-WithError "Python $pyVersion 不满足最低版本要求 ($MIN_PYTHON)，请安装 Python $MIN_PYTHON+ 并加入 PATH"
    }
} catch {
    Exit-WithError "Python not found, please install Python $MIN_PYTHON+ and add to PATH"
}

Write-Host ""

# ============================================================
# 步骤2：检查 Node.js 环境（版本校验 + 可执行性）
# ============================================================
Write-Host "[Check] Node.js environment..."
try {
    $nodeVersionRaw = node --version 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Node.js not found" }
    $nodeVersion = ($nodeVersionRaw -replace 'v', '').Trim()
    Write-Host "[OK] Node.js version: $nodeVersionRaw"
    Write-Log "Node.js check passed: v$nodeVersion"

    if ((Compare-Version $nodeVersion $MIN_NODE) -lt 0) {
        Exit-WithError "Node.js v$nodeVersion 不满足最低版本要求 (v$MIN_NODE)，请安装 Node.js v$MIN_NODE+"
    }
} catch {
    Exit-WithError "Node.js not found, please install Node.js v$MIN_NODE+"
}

Write-Host ""

# ============================================================
# 步骤3：检查包管理器（pnpm → npm 降级）
# ============================================================
Write-Host "[Check] pnpm package manager..."
try {
    $pnpmVersion = pnpm --version 2>$null
    if ($LASTEXITCODE -ne 0) { throw }
    Write-Host "[OK] pnpm version: $pnpmVersion"
    $PKGMGR = "pnpm"
    Write-Log "Using pnpm"
} catch {
    Write-Host "[Warning] pnpm not found, using npm..."
    $PKGMGR = "npm"
    Write-Log "pnpm not found, using npm"
}

Write-Host ""

# ============================================================
# 步骤4：检查并自修复虚拟环境（换机自动重建）
# ============================================================
Write-Host "[Check] Backend virtual environment..."
$venvPython = "backend\venv\Scripts\python.exe"
$needCreateVenv = $false

if (-not (Test-Path $venvPython)) {
    $needCreateVenv = $true
    Write-Host "[Init] Virtual environment not found, creating..."
} else {
    $venvCheck = & $venvPython --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        $needCreateVenv = $true
        Write-Host "[Fix] Virtual environment is broken (Python path invalid), rebuilding..."
        Write-Log "venv broken, rebuilding"
    }
}

if ($needCreateVenv) {
    python -m venv backend\venv --clear
    if ($LASTEXITCODE -ne 0) {
        Exit-WithError "Failed to create virtual environment"
    }
    Write-Host "[OK] Virtual environment created"
    Write-Log "Virtual environment created"
} else {
    Write-Host "[OK] Virtual environment exists and is healthy"
}

# ============================================================
# 步骤5：升级 pip 并安装后端依赖（含镜像回退策略）
# ============================================================
Write-Host ""
Write-Host "[Install] Backend dependencies..."

# 先升级 pip 自身（旧版 pip 可能无法解析现代依赖）
$pipErrorLog = ""
try {
    & $venvPython -m pip install --upgrade pip 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
    Write-Host "  [OK] pip upgraded"
    Write-Log "pip upgraded"
} catch {
    Write-Host "  [Warning] pip upgrade failed, continuing with current version..."
    Write-Log "pip upgrade failed, continuing"
}

# 尝试默认源安装
Write-Host "  [Install] Installing from default PyPI..."
$pipOutput = & $venvPython -m pip install -r backend\requirements.txt 2>&1
$pipExit = $LASTEXITCODE
$pipErrorLog = ($pipOutput | Out-String)

if ($pipExit -eq 0) {
    Write-Host "[OK] Backend dependencies installed"
    Write-Log "Backend dependencies installed from default PyPI"
} else {
    # 默认源失败 → 回退到清华镜像
    Write-Host "  [Retry] Default PyPI failed, trying Tsinghua mirror..."
    Write-Log "pip default failed, trying mirror: $($pipOutput | Select-Object -Last 5)"
    $pipOutput = & $venvPython -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend\requirements.txt 2>&1
    $pipExit = $LASTEXITCODE

    if ($pipExit -eq 0) {
        Write-Host "[OK] Backend dependencies installed (Tsinghua mirror)"
        Write-Log "Backend dependencies installed from Tsinghua mirror"
    } else {
        # 清华镜像也失败 → 输出详细错误
        $pipErrorLog = ($pipOutput | Out-String)
        Write-Host "[Error] Failed to install backend dependencies" -ForegroundColor Red
        Write-Host "  Last 20 lines of pip output:"
        Write-Host "  ----------------------------------------"
        $pipOutput | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" }
        Write-Host "  ----------------------------------------"
        Write-Log "pip install failed (both default and mirror)"
        Write-Log "pip error: $pipErrorLog"
        Write-Host ""
        Write-Host "  Troubleshooting tips:" -ForegroundColor Yellow
        Write-Host "  1. Check network connectivity"
        Write-Host "  2. If graphify build fails, install Visual C++ Build Tools:"
        Write-Host "     https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        Write-Host "  3. Manual install: .\backend\venv\Scripts\pip.exe install -r backend\requirements.txt"
        Exit-WithError "Backend dependency installation failed"
    }
}

Write-Host ""

# ============================================================
# 步骤6：检查并安装前端依赖（含 node_modules 健康校验）
# ============================================================
Write-Host "[Check] Frontend dependencies..."
$needInstall = $false
$nodeModulesPath = "frontend\node_modules"
$nextBinPath = "frontend\node_modules\.bin\next.cmd"

if (-not (Test-Path $nodeModulesPath)) {
    $needInstall = $true
    Write-Host "[Init] node_modules not found, installing..."
} elseif (-not (Test-Path $nextBinPath)) {
    $needInstall = $true
    Write-Host "[Fix] node_modules exists but appears corrupted (next binary missing), reinstalling..."
    Write-Log "node_modules broken, reinstalling"
} else {
    Write-Host "[OK] Frontend dependencies exist and look healthy"
}

if ($needInstall) {
    Set-Location frontend
    Write-Host "  [Install] Running npm install (this may take a while on a new machine)..."
    $npmOutput = & $PKGMGR install 2>&1
    Set-Location ..

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Error] Failed to install frontend dependencies" -ForegroundColor Red
        Write-Host "  Last 20 lines of output:"
        Write-Host "  ----------------------------------------"
        $npmOutput | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" }
        Write-Host "  ----------------------------------------"
        Write-Log "Frontend dependency installation failed"
        Write-Log "npm error: $($npmOutput | Out-String)"
        Write-Host ""
        Write-Host "  Troubleshooting tips:" -ForegroundColor Yellow
        Write-Host "  1. Ensure Node.js v$MIN_NODE+ is installed"
        Write-Host "  2. Try deleting node_modules and running again"
        Write-Host "  3. Check network / npm registry connectivity"
        Exit-WithError "Frontend dependency installation failed"
    }

    Write-Host "[OK] Frontend dependencies installed"
    Write-Log "Frontend dependencies installed"
}

Write-Host ""
Write-Host "============================================"
Write-Host "  Starting services..."
Write-Host "============================================"
Write-Host ""

# ============================================================
# 步骤7：启动 FastAPI 后端（端口 8000）
# ============================================================
Write-Host "[Start] FastAPI backend service (port 8000)..."
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:PSScriptRoot
    & .\backend\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend
}
Write-Log "FastAPI backend started"

Write-Host "[Wait] Waiting for backend to start (5s)..."
Start-Sleep -Seconds 5

# 验证后端健康
Write-Host "[Check] Verifying backend service..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "[OK] Backend service is running"
    Write-Log "Backend health check passed"
} catch {
    Write-Host "[Warning] Backend may not be ready yet, continuing to start frontend..."
    Write-Log "Backend health check failed"
}

# ============================================================
# 步骤8：启动 Next.js 前端（端口 3000）
# ============================================================
Write-Host ""
Write-Host "[Start] Next.js frontend service (port 3000)..."
$frontendJob = Start-Job -ScriptBlock {
    Set-Location "$using:PSScriptRoot\frontend"
    if ($using:PKGMGR -eq "pnpm") {
        pnpm dev
    } else {
        npm run dev
    }
}
Write-Log "Next.js frontend started"

Write-Host "[Wait] Waiting for frontend to start (8s)..."
Start-Sleep -Seconds 8

# 打开浏览器
Write-Host ""
Write-Host "[Open] Starting browser..."
Start-Process "http://localhost:3000"
Write-Log "Browser opened"

Write-Host ""
Write-Host "============================================"
Write-Host "  Gitter services started!"
Write-Host "============================================"
Write-Host ""
Write-Host "  Frontend:  http://localhost:3000"
Write-Host "  Backend:   http://localhost:8000"
Write-Host "  API Docs:  http://localhost:8000/api/docs"
Write-Host ""
Write-Host "  Note: Closing this window will stop all services"
Write-Host "============================================"

Write-Log "Startup completed"

# 保持进程不退出
while ($true) {
    Start-Sleep -Seconds 10
}
