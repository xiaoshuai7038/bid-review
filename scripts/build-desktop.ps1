param(
    [switch]$Clean,
    [ValidateSet("launcher", "standalone")]
    [string]$Mode = "launcher"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Set-Location $ProjectRoot

if ($Clean) {
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BidReviewDesktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktopStandalone" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BidReviewDesktopStandalone" -ErrorAction SilentlyContinue
}

uv sync --extra dev
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SpecPath = if ($Mode -eq "standalone") {
    "$ProjectRoot\scripts\bid_review_desktop.spec"
} else {
    "$ProjectRoot\scripts\bid_review_launcher.spec"
}

uv run --extra dev pyinstaller --noconfirm --clean $SpecPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Desktop bundle ready:" -ForegroundColor Cyan
if ($Mode -eq "standalone") {
    Write-Host "  $ProjectRoot\dist\BidReviewDesktopStandalone\BidReviewDesktopStandalone.exe"
} else {
    Write-Host "  $ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop.exe"
}
