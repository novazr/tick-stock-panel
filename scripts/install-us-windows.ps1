# 美股版一键安装 / 更新 + 启动 (Windows PowerShell)
#
# 用法 (在 PowerShell 里粘贴一行):
#   irm https://raw.githubusercontent.com/novazr/tick-stock-panel/feat/us-market/scripts/install-us-windows.ps1 -OutFile $env:TEMP\tsp-install.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\tsp-install.ps1
# 本文件带 UTF-8 BOM: Windows PowerShell 5.1 按 -File 运行时才能正确读取中文。
#
# 做的事情:
#   1. 缺什么装什么: Git / Node.js LTS / uv (winget), pnpm (npm)
#   2. 代码放到 文档\tick-stock-panel (已存在则 git pull 更新)
#   3. 新开一个窗口运行 dev.ps1 (首次会自动装依赖, 需要几分钟)
#   4. 首次: 数据源切到 Yahoo 美股、跳过向导、加入默认自选、开始同步一年日线
#   5. 打开浏览器 http://localhost:3011
# 可重复运行; 已完成的步骤会自动跳过。

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}

$Repo    = 'https://github.com/novazr/tick-stock-panel.git'
$Branch  = 'feat/us-market'
$Target  = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'tick-stock-panel'
$Api     = 'http://localhost:3018'
$Web     = 'http://localhost:3011'
$Watch   = @('AAPL', 'GOOG', 'NVDA', 'MSFT', 'APP', 'AMZN', 'META', 'TSLA')

function Say($m)  { Write-Host "[安装] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[安装] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[安装] $m" -ForegroundColor Yellow }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Ensure-Tool($cmd, $wingetId, $label, [switch]$Optional) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { Ok "$label 已安装"; return $true }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "没有找到 winget, 请先从 Microsoft Store 安装「应用安装程序 (App Installer)」后重试"
    }
    # 下载服务器偶发 504/超时: 最多重试 3 次
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Say "安装 $label (第 $attempt 次) ..."
        winget install --id $wingetId -e --silent --source winget --accept-package-agreements --accept-source-agreements | Out-Host
        Refresh-Path
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { Ok "$label 安装完成"; return $true }
        if ($attempt -lt 3) { Warn "$label 下载失败, 15 秒后重试"; Start-Sleep -Seconds 15 }
    }
    if ($Optional) { Warn "$label 安装失败, 改用备用方式继续"; return $false }
    throw "$label 连续 3 次下载失败 (多为网络问题)。请稍后重新运行本命令; 若一直失败, 把截图发给 Claude"
}

# ===== 1. 工具 =====
Refresh-Path
$HasGit = Ensure-Tool 'git'  'Git.Git'           'Git' -Optional
$null   = Ensure-Tool 'node' 'OpenJS.NodeJS.LTS' 'Node.js'
$null   = Ensure-Tool 'uv'   'astral-sh.uv'      'uv'
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Say '安装 pnpm ...'
    npm install -g pnpm | Out-Null
    Refresh-Path
    $npmBin = Join-Path $env:APPDATA 'npm'
    if ((Test-Path $npmBin) -and ($env:Path -notlike "*$npmBin*")) { $env:Path = "$env:Path;$npmBin" }
}
Ok 'pnpm 已就绪'

# ===== 2. 代码 =====
function Get-CodeZip {
    # 无 Git 时的备用方式: 下载分支压缩包解压覆盖 (保留目录里已有的数据等其他文件)
    $zip = Join-Path $env:TEMP 'tsp-code.zip'
    $tmp = Join-Path $env:TEMP 'tsp-code'
    $url = "https://codeload.github.com/novazr/tick-stock-panel/zip/refs/heads/$Branch"
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try { Invoke-WebRequest $url -OutFile $zip -UseBasicParsing; break }
        catch { if ($attempt -eq 3) { throw "代码下载失败: $_" }; Warn '代码下载失败, 15 秒后重试'; Start-Sleep -Seconds 15 }
    }
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item (Join-Path $inner.FullName '*') $Target -Recurse -Force
    Remove-Item $tmp -Recurse -Force
    Remove-Item $zip -Force
}

if ($HasGit -and (Test-Path (Join-Path $Target '.git'))) {
    Say "更新代码: $Target"
    git -C $Target fetch origin $Branch
    git -C $Target checkout $Branch
    git -C $Target pull --ff-only origin $Branch
} elseif ($HasGit -and -not (Test-Path $Target)) {
    Say "下载代码到: $Target"
    git clone -b $Branch $Repo $Target
} else {
    Say "下载代码压缩包到: $Target"
    Get-CodeZip
}
Ok '代码已是最新'

# ===== 3. 启动 (新窗口, 保持打开) =====
$running = $false
try { Invoke-RestMethod "$Api/api/settings" -TimeoutSec 3 | Out-Null; $running = $true } catch {}
if ($running) {
    Warn '检测到网站已在运行; 如需加载新代码, 关掉那个窗口后再运行本命令'
} else {
    Say '新开窗口启动网站 (首次会安装依赖, 约 3~10 分钟, 请保持该窗口打开)'
    # dev.ps1 为无 BOM 的 UTF-8; 中文系统的 PowerShell 5.1 会按 GBK 读取导致解析出错。
    # 复制一份带 BOM 的到同目录 (.dev-run.ps1, 已加入 .gitignore) 再运行, 不改动原文件。
    $devSrc = Join-Path $Target 'dev.ps1'
    $devRun = Join-Path $Target '.dev-run.ps1'
    $text = [IO.File]::ReadAllText($devSrc, (New-Object Text.UTF8Encoding $false))
    [IO.File]::WriteAllText($devRun, $text, (New-Object Text.UTF8Encoding $true))
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $devRun + '"'), '-NoReload'
    ) -WorkingDirectory $Target
}

Say '等待后端就绪 ...'
$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    try { $settings = Invoke-RestMethod "$Api/api/settings" -TimeoutSec 3; $ready = $true; break } catch { Start-Sleep -Seconds 5 }
}
if (-not $ready) { throw '15 分钟内后端没有启动, 请把另一个窗口里的报错截图发给 Claude' }
Ok '后端已启动'

# ===== 4. 首次配置 =====
$json = 'application/json; charset=utf-8'
if ($settings.market -ne 'us') {
    Say '数据源切换到 Yahoo 美股'
    Invoke-RestMethod "$Api/api/settings/preferences/data-providers" -Method Put -ContentType $json `
        -Body '{"daily_data_provider":"yahoo_us","adj_factor_provider":"yahoo_us"}' | Out-Null
}
if (-not $settings.onboarding_completed) {
    Invoke-RestMethod "$Api/api/settings/onboarding/complete" -Method Post | Out-Null
}
try {
    $current = Invoke-RestMethod "$Api/api/watchlist" -TimeoutSec 10
    if (-not $current.symbols -or $current.symbols.Count -eq 0) {
        $body = @{ symbols = $Watch } | ConvertTo-Json -Compress
        Invoke-RestMethod "$Api/api/watchlist/batch" -Method Post -ContentType $json -Body $body | Out-Null
        Ok "已加入默认自选: $($Watch -join ', ')"
    }
} catch { Warn "自选添加失败 (可在网页里手动添加): $_" }

$overview = $null
try { $overview = Invoke-RestMethod "$Api/api/overview/market" -TimeoutSec 30 } catch {}
if (-not $overview -or -not $overview.as_of) {
    Say '开始同步美股数据 (518 只股票一年日线, 约 5 分钟, 进度可在网页「数据」页查看)'
    Invoke-RestMethod "$Api/api/pipeline/run" -Method Post -ContentType $json -Body '{}' | Out-Null
}

# ===== 5. 打开网站 =====
Say '等待前端就绪 ...'
for ($i = 0; $i -lt 120; $i++) {
    try { Invoke-WebRequest $Web -UseBasicParsing -TimeoutSec 3 | Out-Null; break } catch { Start-Sleep -Seconds 5 }
}
Start-Process $Web
Ok "完成! 网站: $Web  (另一个 PowerShell 窗口是网站本体, 关掉它网站就停了)"
Ok '以后再次启动或更新: 重新运行同一行安装命令即可'
