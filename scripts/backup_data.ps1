# Nightly local backup of the Golden Vector data store (incident 2026-08-13 prevention).
# Zips data\ to C:\gv_backups\data_<yyyyMMdd_HHmm>.zip and keeps the newest 14.
# Same-disk backups protect against accidental deletion (the 2026-08-13 incident class),
# not against disk failure — an off-machine target remains a recommended follow-up.
$ErrorActionPreference = 'Stop'
$src = 'C:\Users\Emanuel\code\Golden-Vector\data'
$dst = 'C:\gv_backups'
New-Item -ItemType Directory -Path $dst -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmm'
$zip = Join-Path $dst "data_$stamp.zip"
Compress-Archive -Path (Join-Path $src '*') -DestinationPath $zip -CompressionLevel Optimal
Get-ChildItem $dst -Filter 'data_*.zip' | Sort-Object Name -Descending |
    Select-Object -Skip 14 | Remove-Item -Force
