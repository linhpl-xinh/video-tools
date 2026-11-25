# Cập nhật code mới từ GitHub rồi khởi động lại web.
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Resolve-Path (Join-Path $Here "..\..")
if (Test-Path (Join-Path $Repo ".git")) { git -C $Repo pull } else { Write-Host "Thư mục này không phải bản git clone - tải ZIP mới từ GitHub rồi chạy lại." -ForegroundColor Yellow }
robocopy (Join-Path $Repo "plugins\cat-tutorial\skills\cat-tutorial\scripts") "$env:USERPROFILE\.cat-tutorial\app" /MIR /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*ui_server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# start-web.ps1 tự chạy lại sau 5 giây với code mới
Write-Host "Đã cập nhật và khởi động lại web."
