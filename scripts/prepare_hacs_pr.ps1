<#
PowerShell helper: prepare and open a PR to add this repo to the HACS default store (hacs/integration).

Usage:
  1. Ensure `gh` and `git` are installed and you are authenticated (gh auth login).
  2. Run: `.	ools\prepare_hacs_pr.ps1 -Branch add-pow-climate-hacs -DryRun` to preview.
  3. Run without `-DryRun` to fork, clone, add the metadata JSON and open a PR.

This script will:
  - Fork `hacs/integration` to your account and clone it.
  - Create a branch and add `integration/marnixt-powerclimate.json` with repo metadata.
  - Push and open a PR against `hacs/integration:main`.

Note: Review the generated file before creating the PR. If HACS changes their expected file format your manual review is recommended.
#>

param(
    [string]$Branch = "add-pow-climate-hacs",
    [switch]$DryRun
)

$RepoOwner = "marnixt"
$RepoName = "PowerClimate"
$HacsRepo = "hacs/integration"
$Metadata = Get-Content -Raw -Path "$PSScriptRoot\..\..\.github\HACS_INTEGRATION_INFO.json"
$TargetPath = "integration/$RepoOwner-$RepoName.json"

Write-Host "Preparing HACS metadata file at: $TargetPath" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "DRY RUN - printing metadata:\n" -ForegroundColor Yellow
    Write-Host $Metadata
    exit 0
}

Write-Host "Forking and cloning $HacsRepo..." -ForegroundColor Cyan
gh repo fork $HacsRepo --clone=true --remote=true | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to fork/clone $HacsRepo" }

$HacsDir = "$PWD\$(Split-Path -Leaf $HacsRepo)"
Set-Location $HacsDir

git switch -c $Branch

if (-not (Test-Path integration)) { New-Item -ItemType Directory -Path integration | Out-Null }
$FullTarget = Join-Path (Get-Location) $TargetPath
$Metadata | Out-File -Encoding UTF8 -FilePath $FullTarget

git add $TargetPath
git commit -m "Add PowerClimate integration metadata for HACS default store"

git push --set-upstream fork $Branch

Write-Host "Creating PR against $HacsRepo..." -ForegroundColor Cyan
$Title = "Add PowerClimate integration to HACS default store"
$Body = "Add integration listing for marnixt/PowerClimate. See repository HACS_INTEGRATION_INFO.json for metadata." 

gh pr create --base main --head "$RepoOwner:$Branch" --title "$Title" --body "$Body"

Write-Host "PR created. Please review and follow any CI / reviewer comments from the HACS maintainers." -ForegroundColor Green
