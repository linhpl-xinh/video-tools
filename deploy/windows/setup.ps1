# Cài cutpro.asia (bản web Cắt Tutorial) lên máy Windows và cho tự bật khi đăng nhập.
# Chạy: chuột phải "CAI DAT.cmd" -> Run as administrator   (hoặc: powershell -ExecutionPolicy Bypass -File setup.ps1)
# Chạy lại nhiều lần vẫn an toàn.
$ErrorActionPreference = "Stop"
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo    = Resolve-Path (Join-Path $Here "..\..")
$Scripts = Join-Path $Repo "plugins\cat-tutorial\skills\cat-tutorial\scripts"
$Home2   = Join-Path $env:USERPROFILE ".cat-tutorial"
$App     = Join-Path $Home2 "app"
$Venv    = Join-Path $Home2 "venv"
$CfDir   = Join-Path $env:USERPROFILE ".cloudflared"
function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }

Step "1/6 Cài Python, ffmpeg, cloudflared (winget)"
foreach ($id in "Python.Python.3.12", "Gyan.FFmpeg", "Cloudflare.cloudflared", "Git.Git") {
  winget list --id $id -e --accept-source-agreements | Out-Null
  if ($LASTEXITCODE -ne 0) { winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements }
  else { Write-Host "   đã có $id" }
}
RefreshPath
foreach ($c in "ffmpeg", "ffprobe", "cloudflared") { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { throw "Chưa thấy $c trong PATH - đóng cửa sổ, mở lại rồi chạy lại file cài." } }

Step "2/6 Tạo môi trường Python + thư viện (torch, open_clip) - vài phút"
New-Item -ItemType Directory -Force $Home2 | Out-Null
if (-not (Test-Path "$Venv\Scripts\python.exe")) { py -3.12 -m venv $Venv }
& "$Venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -q -r (Join-Path $Scripts "requirements.txt")

Step "3/6 Chép mã chạy vào $App và tải model nhận diện (~600MB, chỉ lần đầu)"
New-Item -ItemType Directory -Force $App | Out-Null
robocopy $Scripts $App /MIR /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
& "$Venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'$App'); import local_detect; local_detect._load(); print('   model sẵn sàng')"

Step "4/6 Khoá đường hầm Cloudflare"
$json = Get-ChildItem $CfDir -Filter *.json -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $json) {
  Write-Host "   Chưa thấy file khoá (.json) trong $CfDir" -ForegroundColor Yellow
  Write-Host "   Chép file <TUNNEL_ID>.json từ USB vào $CfDir rồi chạy lại file cài." -ForegroundColor Yellow
  exit 1
}
$tid = $json.BaseName
@"
tunnel: $tid
credentials-file: $($json.FullName)
ingress:
  - hostname: cutpro.asia
    service: http://127.0.0.1:8790
  - hostname: www.cutpro.asia
    service: http://127.0.0.1:8790
  - service: http_status:404
"@ | Set-Content -Encoding ascii (Join-Path $CfDir "config.yml")
Write-Host "   tunnel $tid"

Step "5/6 Cho web + đường hầm tự bật khi đăng nhập Windows (Task Scheduler)"
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$trg = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$ps  = "powershell.exe"
$web = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Here\start-web.ps1`""
$tun = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Here\start-tunnel.ps1`""
Register-ScheduledTask -TaskName "cutpro-web"    -Action $web -Trigger $trg -Settings $set -Force | Out-Null
Register-ScheduledTask -TaskName "cutpro-tunnel" -Action $tun -Trigger $trg -Settings $set -Force | Out-Null
Start-ScheduledTask -TaskName "cutpro-web"; Start-ScheduledTask -TaskName "cutpro-tunnel"

Step "6/6 Không cho máy ngủ khi cắm điện (web tắt nếu máy ngủ)"
$a = Read-Host "   Đặt Windows không bao giờ ngủ khi cắm điện? (Y/n)"
if ($a -ne "n") { powercfg /change standby-timeout-ac 0; powercfg /change hibernate-timeout-ac 0; Write-Host "   đã đặt" }

Start-Sleep 8
try { $r = Invoke-WebRequest http://127.0.0.1:8790/ -UseBasicParsing -TimeoutSec 10; Write-Host "`nWeb trên máy: OK ($($r.StatusCode))" -ForegroundColor Green }
catch { Write-Host "`nWeb chưa lên - xem $Home2\web.log" -ForegroundColor Red }
Write-Host "Kiểm tra từ ngoài: https://cutpro.asia   (nhật ký: $Home2\web.log, $Home2\tunnel.log)"
