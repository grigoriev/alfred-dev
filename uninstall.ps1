# ---------------------------------------------------------------------------
# Alfred Dev -- uninstall script (Windows)
#
# Usage:
#   irm https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/uninstall.ps1 | iex
#
# Strategy:
#   1. If Claude CLI is available, uninstall the plugin and remove the
#      marketplace the native way.
#   2. Remove any leftover files in cache/ and marketplaces/.
#   3. Clean the internal JSON files if traces remain.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$PluginName = "alfred-dev"
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
$PluginsDir = Join-Path $ClaudeDir "plugins"
# The cache path follows the Claude Code convention: cache/<marketplace>/<plugin>/<version>.
# Delete the whole marketplace directory to cover old and new installs.
$CacheDir = Join-Path $PluginsDir "cache" $PluginName
$MarketplaceDir = Join-Path $PluginsDir "marketplaces" $PluginName
$InstalledFile = Join-Path $PluginsDir "installed_plugins.json"
$KnownMarketplaces = Join-Path $PluginsDir "known_marketplaces.json"
$SettingsFile = Join-Path $ClaudeDir "settings.json"
$PluginKey = "$PluginName@$PluginName"
$GlobalAliasDir = Join-Path $ClaudeDir "skills/alfred"
$GlobalAliasFile = Join-Path $GlobalAliasDir "SKILL.md"
$GlobalCommandAliasDir = Join-Path $ClaudeDir "commands"
$GlobalCommandAliasFile = Join-Path $GlobalCommandAliasDir "alfred.md"

# -- Helper functions -----------------------------------------------------

function Write-Info  { param([string]$Msg) Write-Host ">" $Msg -ForegroundColor Blue }
function Write-Ok    { param([string]$Msg) Write-Host "+" $Msg -ForegroundColor Green }
function Write-Err   { param([string]$Msg) Write-Host "x" $Msg -ForegroundColor Red }

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        return (Get-Content $Path -Raw -Encoding UTF8) | ConvertFrom-Json
    }
    catch {
        Write-Err "В файле '$Path' некорректный JSON: $_"
        throw
    }
}

# Write JSON atomically (temp file in the same directory + move).
# A temp file next to the target makes Move-Item an atomic file system
# rename, with no copy between disks.
function Write-JsonFileAtomic {
    param([string]$Path, [object]$Data)
    $targetDir = Split-Path $Path -Parent
    $tmpFile = Join-Path $targetDir ".tmp-$([System.IO.Path]::GetRandomFileName())"
    try {
        $Data | ConvertTo-Json -Depth 10 | Set-Content $tmpFile -Encoding UTF8
        Move-Item -Path $tmpFile -Destination $Path -Force
    }
    catch {
        if (Test-Path $tmpFile) { Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Test-EmptyDirectory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    return $null -eq (Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
}

function Remove-GlobalAlfredAlias {
    $removed = $false

    if (Test-Path $GlobalAliasFile -PathType Leaf) {
        $content = Get-Content $GlobalAliasFile -Raw -Encoding UTF8
        if ($content -match "Alfred Dev global alias") {
            Remove-Item $GlobalAliasFile -Force
            if (Test-EmptyDirectory $GlobalAliasDir) {
                Remove-Item $GlobalAliasDir -Force
            }
            Write-Ok "Глобальный alias /alfred удалён"
            $removed = $true
        }
        else {
            Write-Info "${GlobalAliasFile} сохранён: похоже, это не alias Alfred Dev"
        }
    }

    if (Test-Path $GlobalCommandAliasFile -PathType Leaf) {
        $content = Get-Content $GlobalCommandAliasFile -Raw -Encoding UTF8
        if ($content -match "Alfred Dev global alias") {
            Remove-Item $GlobalCommandAliasFile -Force
            if (Test-EmptyDirectory $GlobalCommandAliasDir) {
                Remove-Item $GlobalCommandAliasDir -Force
            }
            Write-Ok "Глобальный shim команды /alfred удалён"
            $removed = $true
        }
        else {
            Write-Info "${GlobalCommandAliasFile} сохранён: похоже, это не alias Alfred Dev"
        }
    }

    if (-not $removed) {
        Write-Info "Глобальный alias /alfred не найден"
    }
}

# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Удаляю Alfred Dev" -ForegroundColor White
Write-Host ""

# Try the canonical Claude Code way first.
$ClaudeCli = Get-Command claude -ErrorAction SilentlyContinue
if ($null -ne $ClaudeCli) {
    Write-Info "Удаляю плагин через Claude CLI..."
    & claude plugin uninstall $PluginKey --scope user 2>&1 | Out-Null
    & claude plugin marketplace remove $PluginName --scope user 2>&1 | Out-Null
    Write-Ok "Claude CLI попытался снять регистрацию плагина и marketplace"
}
else {
    Write-Info "Команда 'claude' недоступна; выполняю ручную страховочную очистку"
}

# Remove the plugin cache
if (Test-Path $CacheDir) {
    Remove-Item $CacheDir -Recurse -Force
    Write-Ok "Cache плагина удалён"
}
else {
    Write-Info "Cache плагина не найден"
}

# Remove the marketplace directory
if (Test-Path $MarketplaceDir) {
    Remove-Item $MarketplaceDir -Recurse -Force
    Write-Ok "Каталог marketplace удалён"
}
else {
    Write-Info "Каталог marketplace не найден"
}

Remove-GlobalAlfredAlias

# Remove the marketplace from known_marketplaces.json
if (Test-Path $KnownMarketplaces) {
    $known = Read-JsonFile $KnownMarketplaces
    if ($null -ne $known -and $known.PSObject.Properties.Name -contains $PluginName) {
        $known.PSObject.Properties.Remove($PluginName)
        Write-JsonFileAtomic $KnownMarketplaces $known
        Write-Ok "Marketplace удалён из known_marketplaces.json"
    }
}

# Remove the entry from installed_plugins.json
if (Test-Path $InstalledFile) {
    $installed = Read-JsonFile $InstalledFile
    if ($null -ne $installed -and
        $installed.PSObject.Properties.Name -contains 'plugins' -and
        $installed.plugins.PSObject.Properties.Name -contains $PluginKey) {
        $installed.plugins.PSObject.Properties.Remove($PluginKey)
        Write-JsonFileAtomic $InstalledFile $installed
        Write-Ok "Запись удалена из installed_plugins.json"
    }
}

# Disable in settings.json
if (Test-Path $SettingsFile) {
    $settings = Read-JsonFile $SettingsFile
    if ($null -ne $settings -and
        $settings.PSObject.Properties.Name -contains 'enabledPlugins' -and
        $settings.enabledPlugins.PSObject.Properties.Name -contains $PluginKey) {
        $settings.enabledPlugins.PSObject.Properties.Remove($PluginKey)
        Write-JsonFileAtomic $SettingsFile $settings
        Write-Ok "Плагин удалён из settings.json"
    }
}
else {
    Write-Info "settings.json не найден (отключать нечего)"
}

Write-Host ""
Write-Host "Alfred Dev удалён" -ForegroundColor Green
Write-Host "  Перезапусти Claude Code, чтобы применить изменения." -ForegroundColor DarkGray
Write-Host ""
