# Build windowed exe: dist\JiXingModHelper\JiXingModHelper.exe  (NO console / NO cmd)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> deps"
python -m pip install -q -r requirements.txt
python -m pip install -q "pyinstaller>=6.0"

Write-Host "==> clean"
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path "dist\JiXingModHelper") { Remove-Item -Recurse -Force "dist\JiXingModHelper" }

Write-Host "==> pyinstaller"
python -m PyInstaller --noconfirm --clean build_exe.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$out = Join-Path $PSScriptRoot "dist\JiXingModHelper"
$exe = Join-Path $out "JiXingModHelper.exe"
$tpk = Join-Path $out "_internal\UnityPy\resources\lzma.tpk"
$web = Join-Path $out "_internal\astral_party_auto\webui\index.html"

if (-not (Test-Path $exe)) { throw "missing exe" }
if (-not (Test-Path $tpk)) { throw "missing UnityPy resources\lzma.tpk - package broken" }
if (-not (Test-Path $web)) { throw "missing webui" }

Write-Host "OK exe:" $exe
Write-Host "OK tpk:" $tpk
Write-Host "Double-click JiXingModHelper.exe (no cmd). Copy whole folder."
