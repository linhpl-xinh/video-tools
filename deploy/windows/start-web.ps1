# Chạy bản web Cắt Tutorial (Task Scheduler gọi file này khi đăng nhập).
$Home2 = Join-Path $env:USERPROFILE ".cat-tutorial"
$env:CAT_TUTORIAL_WEB = "1"; $env:CAT_TUTORIAL_PORT = "8790"; $env:PYTHONIOENCODING = "utf-8"
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
while ($true) {   # tắt ngang thì tự chạy lại sau 5 giây
  & "$Home2\venv\Scripts\python.exe" -I "$Home2\app\ui_server.py" *>> "$Home2\web.log"
  Start-Sleep 5
}
