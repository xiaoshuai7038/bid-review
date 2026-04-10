[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Name,

    [string]$RepoRoot = '',

    [string]$RootDir = '',

    [string]$BaseBranch = '',

    [switch]$CheckoutNewBranch,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$RawRepoRoot)

    if ($RawRepoRoot) {
        return (Resolve-Path -LiteralPath $RawRepoRoot).ProviderPath
    }

    $repoHint = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
    $scriptRepoRoot = (& git -C $repoHint rev-parse --show-toplevel).Trim()
    if (-not $scriptRepoRoot) {
        throw 'Unable to resolve repo root.'
    }
    return $scriptRepoRoot
}

function Resolve-BaseBranch {
    param(
        [string]$ResolvedRepoRoot,
        [string]$RawBaseBranch
    )

    if ($RawBaseBranch) {
        return $RawBaseBranch.Trim()
    }

    $current = (& git -C $ResolvedRepoRoot branch --show-current).Trim()
    if ($current) {
        return $current
    }

    return 'main'
}

function Normalize-BranchName {
    param([string]$RawName)

    $normalized = $RawName -replace '[^A-Za-z0-9._/-]', '-'
    $normalized = $normalized.Trim('-')
    if (-not $normalized) {
        return 'agent/worktree'
    }
    return ('agent/' + $normalized)
}

function New-AgentEnvContent {
    param(
        [string]$RuntimeRoot,
        [string]$RunContextRoot
    )

    return (
        '$env:BID_REVIEW_RUNTIME_ROOT = "' + $RuntimeRoot + '"' + [Environment]::NewLine +
        '$env:BID_REVIEW_RUN_CONTEXT_DIR = "' + $RunContextRoot + '"'
    )
}

$resolvedRepoRoot = Resolve-RepoRoot -RawRepoRoot $RepoRoot
$resolvedBaseBranch = Resolve-BaseBranch -ResolvedRepoRoot $resolvedRepoRoot -RawBaseBranch $BaseBranch
$resolvedRootDir = if ($RootDir) {
    [System.IO.Path]::GetFullPath($RootDir)
} else {
    Join-Path (Split-Path -Parent $resolvedRepoRoot) 'bidreview-worktrees'
}
$worktreePath = [System.IO.Path]::GetFullPath((Join-Path $resolvedRootDir $Name))
$runtimeRoot = [System.IO.Path]::GetFullPath((Join-Path $worktreePath '.runtime'))
$runContextRoot = [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot 'review-context'))
$envScriptPath = [System.IO.Path]::GetFullPath((Join-Path $worktreePath 'agent-env.ps1'))
$branchName = Normalize-BranchName -RawName $Name

if ($DryRun) {
    Write-Output 'mode: dry-run'
    Write-Output ('repo_root: ' + $resolvedRepoRoot)
    Write-Output ('base_branch: ' + $resolvedBaseBranch)
    Write-Output ('branch_name: ' + $branchName)
    Write-Output ('worktree_path: ' + $worktreePath)
    Write-Output ('runtime_root: ' + $runtimeRoot)
    Write-Output ('run_context_root: ' + $runContextRoot)
    Write-Output ('env_script: ' + $envScriptPath)
    exit 0
}

New-Item -ItemType Directory -Path $resolvedRootDir -Force | Out-Null
if (Test-Path -LiteralPath $worktreePath) {
    throw ('Target worktree path already exists: ' + $worktreePath)
}

$gitArgs = @('-C', $resolvedRepoRoot, 'worktree', 'add')
if ($CheckoutNewBranch) {
    $gitArgs += @('-b', $branchName)
}
$gitArgs += @($worktreePath, $resolvedBaseBranch)
& git @gitArgs
if ($LASTEXITCODE -ne 0) {
    throw 'git worktree add failed.'
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runContextRoot -Force | Out-Null
New-AgentEnvContent -RuntimeRoot $runtimeRoot -RunContextRoot $runContextRoot | Set-Content -LiteralPath $envScriptPath -Encoding UTF8

Write-Output 'mode: created'
Write-Output ('repo_root: ' + $resolvedRepoRoot)
Write-Output ('base_branch: ' + $resolvedBaseBranch)
Write-Output ('branch_name: ' + $branchName)
Write-Output ('worktree_path: ' + $worktreePath)
Write-Output ('runtime_root: ' + $runtimeRoot)
Write-Output ('run_context_root: ' + $runContextRoot)
Write-Output ('env_script: ' + $envScriptPath)
