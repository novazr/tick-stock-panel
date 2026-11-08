# 在 Windows 上运行美股版（`feat/us-market` 分支）

适用于还在改造中的美股版本。上游的 Windows 安装包不含这些改动，所以用源码方式运行。

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
| 看板顶部还是上证、深成等 A 股指数 | 首页指数固定为 A 股四只 | 阶段 1c 改为 SPY / QQQ 等 |
| 涨红跌绿 | 沿用 A 股配色 | 阶段 2 按市场切换 |
| 成交额显示 0 或 — | Yahoo 不提供成交额 | 换付费数据源后补齐 |
| 成交量单位是「手」（100 股） | 项目内部统一按手计量 | 阶段 2 按市场显示 |
| 没有实时行情和分时图 | Yahoo 插件只提供日线 | 阶段 3 评估数据源 |
| 连板、涨停梯队等 A 股功能 | 美股没有涨跌停 | 美股实例中隐藏 |
