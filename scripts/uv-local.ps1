$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LocalTmp = Join-Path $ProjectRoot ".local_tmp"

New-Item -ItemType Directory -Force -Path $LocalTmp | Out-Null

$env:UV_CACHE_DIR = Join-Path $LocalTmp "uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $LocalTmp "uv-python"
$env:TEMP = Join-Path $LocalTmp "temp"
$env:TMP = Join-Path $LocalTmp "temp"
$env:TMPDIR = Join-Path $LocalTmp "temp"

New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:UV_PYTHON_INSTALL_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null

& uv @args
exit $LASTEXITCODE
