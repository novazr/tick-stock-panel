@echo off
rem Double-click to start tick-stock-panel (backend 3018 + web 3011). Keep this window open.
cd /d "%~dp0"
powershell -NoProfile -Command "$t=[IO.File]::ReadAllText('dev.ps1',(New-Object Text.UTF8Encoding $false));[IO.File]::WriteAllText('.dev-run.ps1',$t,(New-Object Text.UTF8Encoding $true))"
start "" /min powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest http://localhost:3011 -UseBasicParsing -TimeoutSec 3 | Out-Null; Start-Process http://localhost:3011; break}catch{Start-Sleep 5}}"
powershell -NoExit -ExecutionPolicy Bypass -File ".dev-run.ps1" -NoReload -Force
