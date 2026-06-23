$ErrorActionPreference = "Stop"
$icon = if ($env:JARVIX_ICON) { $env:JARVIX_ICON } else { "" }
$arguments = @(
    "--noconfirm",
    "--onedir",
    "--windowed",
    "--name", "Jarvix",
    "jarvix_desktop.py"
)
if ($icon -and (Test-Path -LiteralPath $icon)) {
    $arguments = @("--icon", $icon) + $arguments
}
$python = if (Test-Path -LiteralPath "..\..\.venv\Scripts\python.exe") {
    Resolve-Path "..\..\.venv\Scripts\python.exe"
} else {
    "python"
}
& $python -m PyInstaller @arguments
