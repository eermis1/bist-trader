# Runs the dashboard cycle, republishes docs/index.html (GitHub Pages
# source), and pushes state/log/docs changes to GitHub so the public
# dashboard (https://eermis1.github.io/bist-trader/) stays in sync from
# this PC's own scheduled runs -- the Claude cloud routine can't be used
# here because that sandbox's network policy blocks Yahoo Finance/TEFAS.
$ErrorActionPreference = "Stop"
$repoRoot = "C:\Users\evren\OneDrive\Desktop\Agent_Workspace\bist_trader"
Set-Location $repoRoot

& "$repoRoot\.venv\Scripts\python.exe" "$repoRoot\scripts\run_dashboard_cycle.py"

Copy-Item "$repoRoot\reports\dashboard.html" "$repoRoot\docs\index.html" -Force

git add data/state data/logs/*.csv docs/index.html
$staged = git diff --cached --name-only
if ($staged) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm"
    git commit -m "Dashboard cycle: $ts (local PC)`n`nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>" -q
    git push origin master -q
} else {
    Write-Output "No changes to publish this cycle."
}
