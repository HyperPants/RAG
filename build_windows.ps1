param(
    [string]$OutputDirectory = 'dist',
    [string]$BuildDirectory = 'build'
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Create the project Windows virtual environment and install its requirements first.'
    }

    $options = @(
        '--noconfirm', '--onedir', '--windowed', '--noupx', '--name', 'Atlas',
        '--icon', (Join-Path $PSScriptRoot 'src/api/web/atlas.ico'),
        '--distpath', $OutputDirectory, '--workpath', $BuildDirectory, '--specpath', $BuildDirectory,
        '--add-data', ((Join-Path $PSScriptRoot "config.yaml") + ":."), '--add-data', ((Join-Path $PSScriptRoot "src/api/web") + ":src/api/web"),
        '--hidden-import', 'uvicorn.loops.asyncio', '--hidden-import', 'uvicorn.protocols.http.h11_impl',
        '--hidden-import', 'uvicorn.lifespan.on', (Join-Path $PSScriptRoot "desktop_windows.py")
    )
    & $python -m PyInstaller @options
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to build Atlas.' }
}
finally {
    Pop-Location
}
