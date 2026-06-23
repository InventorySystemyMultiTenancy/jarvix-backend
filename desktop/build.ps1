$ErrorActionPreference = "Stop"
$icon = if ($env:JARVIX_ICON) { $env:JARVIX_ICON } else { "" }
$python = if ($env:JARVIX_BUILD_PYTHON) {
    $env:JARVIX_BUILD_PYTHON
} elseif (Test-Path -LiteralPath "..\..\.venv\Scripts\python.exe") {
    Resolve-Path "..\..\.venv\Scripts\python.exe"
} else {
    "python"
}

$arguments = @(
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "Jarvix",
    "jarvix_desktop.py"
)
if ($icon -and (Test-Path -LiteralPath $icon)) {
    $arguments = @("--icon", $icon) + $arguments
}
& $python -m PyInstaller @arguments
