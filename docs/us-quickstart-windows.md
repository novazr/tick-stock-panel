# 在 Windows 上运行美股版（`feat/us-market` 分支）

适用于还在改造中的美股版本。上游的 Windows 安装包不含这些改动，所以用源码方式运行。

## 最快方式：一行命令

打开 **PowerShell**（开始菜单搜索 PowerShell），粘贴下面这一行回车：

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/novazr/tick-stock-panel/feat/us-market/scripts/install-us-windows.ps1 | iex"
```

脚本会自动安装缺少的工具、下载代码、新开一个窗口启动网站、切换到 Yahoo 美股数据源、开始同步数据，并打开浏览器。
以后要启动或更新，重新运行同一行即可。下面是手动步骤，脚本出问题时再看。

## 1. 一次性安装工具

打开 **PowerShell**（开始菜单搜索 PowerShell），依次执行：

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id astral-sh.uv -e
```

装完**关掉 PowerShell 再重新打开**，然后：

```powershell
npm install -g pnpm
```

`uv` 会自动下载项目需要的 Python，不需要单独安装 Python。

## 2. 下载代码

```powershell
cd $HOME\Documents
git clone -b feat/us-market https://github.com/novazr/tick-stock-panel.git
cd tick-stock-panel
```

## 3. 启动

```powershell
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

第一次启动会自动安装依赖，需要几分钟。看到下面两行就是启动好了：

```text
|  backend   http://localhost:3018
|  frontend  http://localhost:3011
```

用浏览器打开 **http://localhost:3011**。这个 PowerShell 窗口要一直开着，关掉网站就停了。

## 4. 第一次使用

1. 按向导走到「数据源 / 能力路由」：**日K** 和 **除权因子** 都选 **Yahoo Finance（美股）**，其余保持默认，点完成
2. 左上角点「数据」→ 运行同步：会拉取标普 500 + 纳指 100 共 518 只股票的一年日线和拆股分红，约 5 分钟
3. 同步完成后，在「自选」里添加代码（如 `AAPL`、`BRK-B`）即可看 K 线和指标

追加不在标普 500 / 纳指 100 里的股票：在数据目录的 `user_data\yahoo_us_symbols.txt` 里每行写一个代码，下次同步时生效。数据目录位置在「设置 → 数据源」顶部可以看到。

## 5. 更新到最新版本

```powershell
cd $HOME\Documents\tick-stock-panel
git pull
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

## 当前已知限制

| 现象 | 原因 | 计划 |
| --- | --- | --- |
| 成交额是估算值（单位美元，界面仍显示「亿」） | Yahoo 不提供成交额，用「股数 × (高+低+收)/3」估算，大盘股误差约 1~2% | 换付费数据源后用真实值 |
| 没有实时行情和分时图 | Yahoo 插件只提供日线 | 阶段 3 评估数据源 |
| 换手率为 0 | 缺少流通股本数据 | 后续补流通股本 |
| 大盘指标卡里的涨停/连板数恒为 0 | 美股没有涨跌停 | 后续替换为美股指标 |
| 「数据修正」补数后看板没刷新 | 进程内缓存未失效 | 重启服务即可，后续修复 |

已完成：首页指数为 SPY / QQQ / DIA / IWM；绿涨红跌；成交量按「股」显示；
涨停梯队、概念/行业热度组件和连板梯队、概念/行业分析页面在美股实例中自动隐藏。
