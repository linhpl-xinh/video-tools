# Chạy đường hầm Cloudflare cho cutpro.asia.
$Home2 = Join-Path $env:USERPROFILE ".cat-tutorial"
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
while ($true) {
  cloudflared tunnel --config "$env:USERPROFILE\.cloudflared\config.yml" run *>> "$Home2\tunnel.log"
  Start-Sleep 5
}
