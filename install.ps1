# ---------------------------------------------------------------------------
# Alfred Dev -- install script for Claude Code (Windows)
#
# Usage:
#   irm https://raw.githubusercontent.com/grigoriev/alfred-dev/main/install.ps1 | iex
#
# What it does:
#   1. Checks that Claude Code is installed
#   2. Registers the plugin GitHub source globally in Claude Code
#   3. Installs the plugin with claude plugin install
#   4. Does not touch ~/.claude/skills and does not install a global /alfred alias
#   5. Ready to use: /alfred-dev:alfred
#
# The script delegates all management to the native Claude Code CLI
# (claude plugin marketplace / claude plugin install). It registers a
# custom, unofficial GitHub source and stays compatible with future versions.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$Repo = "grigoriev/alfred-dev"
$PluginName = "alfred-dev"
$Version = "0.10.0"

# -- Helper functions -----------------------------------------------------

function Write-Info  { param([string]$Msg) Write-Host ">" $Msg -ForegroundColor Blue }
function Write-Ok    { param([string]$Msg) Write-Host "+" $Msg -ForegroundColor Green }
function Write-Err   { param([string]$Msg) Write-Host "x" $Msg -ForegroundColor Red }

function Get-CompatiblePython {
    $candidates = @(
        @{ Display = "py -3.13"; Command = "py"; LauncherArg = "-3.13" },
        @{ Display = "py -3.12"; Command = "py"; LauncherArg = "-3.12" },
        @{ Display = "py -3.11"; Command = "py"; LauncherArg = "-3.11" },
        @{ Display = "py -3.10"; Command = "py"; LauncherArg = "-3.10" },
        @{ Display = "python3"; Command = "python3" },
        @{ Display = "python"; Command = "python" }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }

        try {
            $args = @()
            if ($candidate.ContainsKey("LauncherArg")) {
                $args += $candidate.LauncherArg
            }
            $args += @(
                "-c",
                'import sys; print(sys.executable); print("{}.{}".format(sys.version_info.major, sys.version_info.minor))'
            )

            $output = & $candidate.Command @args 2>$null
            if ($LASTEXITCODE -ne 0 -or $null -eq $output -or $output.Count -lt 2) {
                continue
            }

            $pythonPath = "$($output[0])".Trim()
            $version = "$($output[1])".Trim()
            $parts = $version -split '\.'
            if ($parts.Count -lt 2) {
                continue
            }

            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                return @{
                    DisplayCommand = $candidate.Display
                    ExecutablePath = $pythonPath
                    Version = $version
                }
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Write-TextFileAtomic {
    param([string]$Path, [string]$Content)
    $targetDir = Split-Path $Path -Parent
    $tmpFile = Join-Path $targetDir ".tmp-$([System.IO.Path]::GetRandomFileName())"
    try {
        [System.IO.File]::WriteAllText($tmpFile, $Content, [System.Text.Encoding]::UTF8)
        Move-Item -Path $tmpFile -Destination $Path -Force
    }
    catch {
        if (Test-Path $tmpFile) { Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Get-InstalledPluginRoot {
    param(
        [string]$ClaudeDir,
        [string]$PluginName,
        [string]$Version
    )

    $cacheDir = Join-Path $ClaudeDir "plugins/cache/$PluginName"
    $exact = Join-Path $cacheDir "$PluginName/$Version"
    $legacy = Join-Path $cacheDir $Version

    if (Test-Path $exact -PathType Container) { return $exact }
    if (Test-Path $legacy -PathType Container) { return $legacy }
    if (-not (Test-Path $cacheDir -PathType Container)) { return $null }

    $candidates = Get-ChildItem -Path $cacheDir -Filter plugin.json -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*\.claude-plugin\*" } |
        Sort-Object LastWriteTimeUtc -Descending

    foreach ($candidate in $candidates) {
        try {
            $data = (Get-Content $candidate.FullName -Raw -Encoding UTF8) | ConvertFrom-Json
        }
        catch {
            continue
        }

        if ($data.version -ne $Version) {
            continue
        }

        return Split-Path (Split-Path $candidate.FullName -Parent) -Parent
    }

    return $null
}

function Test-GlobalSourceRegistration {
    param(
        [string]$ClaudeDir,
        [string]$PluginName,
        [string]$Repo
    )

    $knownMarketplaces = Join-Path $ClaudeDir "plugins/known_marketplaces.json"
    if (-not (Test-Path $knownMarketplaces -PathType Leaf)) {
        return $false
    }

    try {
        $data = (Get-Content $knownMarketplaces -Raw -Encoding UTF8) | ConvertFrom-Json
    }
    catch {
        return $false
    }

    if (-not $data.PSObject.Properties.Name.Contains($PluginName)) {
        return $false
    }

    $entry = $data.$PluginName
    return $entry.source.source -eq "github" -and $entry.source.repo -eq $Repo
}

function Normalize-ToUserScopeInstallation {
    param(
        [string]$PluginName,
        [string]$PluginKey
    )

    # Alfred Dev supports only a global user install. If someone installed it
    # before in local/project scope, clean up that trace in the current context
    # before reinstalling with --scope user.
    & claude plugin uninstall $PluginKey --scope local 2>&1 | Out-Null
    & claude plugin uninstall $PluginKey --scope project 2>&1 | Out-Null
    & claude plugin marketplace remove $PluginName --scope local 2>&1 | Out-Null
    & claude plugin marketplace remove $PluginName --scope project 2>&1 | Out-Null
    Write-Ok "Scopes local/project нормализованы; Alfred будет установлен глобально для пользователя"
}

function Remove-StaleUserMarketplaceCheckout {
    param(
        [string]$ClaudeDir,
        [string]$PluginName
    )

    $marketplaceDir = Join-Path $ClaudeDir "plugins/marketplaces/$PluginName"
    if (Test-Path $marketplaceDir -PathType Container) {
        Remove-Item -Path $marketplaceDir -Recurse -Force
        Write-Ok "Локальный checkout marketplace очищен, чтобы не было устаревшего cache"
    }
}

function Update-UserMarketplace {
    param([string]$PluginName)

    $updateResult = & claude plugin marketplace update $PluginName 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Локальный marketplace обновлён"
    }
    else {
        Write-Info "Не удалось выполнить 'claude plugin marketplace update'; продолжаю с только что зарегистрированным checkout"
    }
}

function Assert-UserScopeInstallation {
    param([string]$PluginKey)

    $pluginListJson = & claude plugin list --json 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Не удалось подтвердить глобальный scope через 'claude plugin list --json'"
        Write-Err "Alfred Dev должен быть установлен со scope user."
        exit 1
    }

    try {
        $entries = @(($pluginListJson | Out-String) | ConvertFrom-Json)
    }
    catch {
        Write-Err "Некорректный JSON в claude plugin list --json: $_"
        exit 1
    }

    $matches = @($entries | Where-Object { $_.id -eq $PluginKey })
    if ($matches.Count -eq 0) {
        Write-Err "$PluginKey нет в claude plugin list --json"
        exit 1
    }

    $activeNonUser = @($matches | Where-Object { $_.enabled -eq $true -and $_.scope -ne "user" })
    if ($activeNonUser.Count -gt 0) {
        $details = @($activeNonUser | ForEach-Object {
            "scope=$($_.scope) projectPath=$($_.projectPath)"
        }) -join ", "
        Write-Err "Есть активные неглобальные установки ${PluginKey}: $details"
        exit 1
    }

    $enabledUser = @($matches | Where-Object { $_.enabled -eq $true -and $_.scope -eq "user" })
    if ($enabledUser.Count -eq 0) {
        $scopes = @($matches | ForEach-Object { "$($_.scope)" }) -join ", "
        Write-Err "$PluginKey есть, но нет записи enabled со scope user. Найденные scopes: $scopes"
        exit 1
    }

    $staleNonUser = @($matches | Where-Object { $_.enabled -ne $true -and $_.scope -ne "user" })
    if ($staleNonUser.Count -gt 0) {
        $details = @($staleNonUser | ForEach-Object {
            "scope=$($_.scope) projectPath=$($_.projectPath)"
        }) -join ", "
        Write-Info "ВНИМАНИЕ: остались старые неактивные записи ${PluginKey}: $details"
    }

    Write-Ok "Глобальная установка для пользователя подтверждена (--scope user)"
}

# -- Checks ----------------------------------------------------------------

$Python = Get-CompatiblePython
if ($null -eq $Python) {
    Write-Err "Python 3.10 или новее не найден"
    Write-Err "Искали: py -3.13, py -3.12, py -3.11, py -3.10, python3, python"
    Write-Err "Alfred Dev нужен Python для hooks, core и MCP, в том числе на Windows"
    exit 1
}

Write-Ok "Найден Python $($Python.Version) ($($Python.DisplayCommand))"

if (-not $env:USERPROFILE -or -not (Test-Path $env:USERPROFILE -PathType Container)) {
    Write-Err "USERPROFILE не задан или не указывает на существующий каталог"
    exit 1
}

$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
if (-not (Test-Path $ClaudeDir)) {
    Write-Err "Каталог $ClaudeDir не найден"
    Write-Err "Убедись, что Claude Code установлен: https://code.claude.com/docs/en/setup"
    exit 1
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Err "Команды 'claude' нет в PATH"
    Write-Err "Убедись, что Claude Code установлен и доступен из терминала"
    exit 1
}

# -- Install ----------------------------------------------------------------

Write-Host ""
Write-Host "Alfred Dev" -ForegroundColor White -NoNewline
Write-Host " v$Version" -ForegroundColor DarkGray
Write-Host "Плагин автоматизированной разработки ПО" -ForegroundColor DarkGray
Write-Host ""

# -- 1. Register the global source in Claude Code ---------------------------

Write-Info "Регистрирую глобальный GitHub-источник в Claude Code..."

$pluginKey = "$PluginName@$PluginName"
Normalize-ToUserScopeInstallation -PluginName $PluginName -PluginKey $pluginKey

$pluginList = & claude plugin list 2>&1
if ($pluginList -match [regex]::Escape($pluginKey)) {
    & claude plugin uninstall $pluginKey --scope user 2>&1 | Out-Null
}

$marketplaceList = & claude plugin marketplace list 2>&1
if ($marketplaceList -match $PluginName) {
    & claude plugin marketplace remove $PluginName --scope user 2>&1 | Out-Null
}
Remove-StaleUserMarketplaceCheckout -ClaudeDir $ClaudeDir -PluginName $PluginName

$marketplaceResult = & claude plugin marketplace add $Repo --scope user 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "GitHub-источник объявлен"
}
else {
    Write-Err "Не удалось зарегистрировать GitHub-источник"
    Write-Err "Проверь подключение к интернету и доступность репозитория:"
    Write-Err "  https://github.com/$Repo"
    exit 1
}

if (Test-GlobalSourceRegistration -ClaudeDir $ClaudeDir -PluginName $PluginName -Repo $Repo) {
    Write-Ok "GitHub-источник зарегистрирован глобально"
}
else {
    Write-Info "CLI ответил OK, но источник не зарегистрирован; пробую снова..."
    & claude plugin marketplace remove $PluginName --scope user 2>&1 | Out-Null
    $marketplaceResult = & claude plugin marketplace add $Repo --scope user 2>&1
    if ($LASTEXITCODE -eq 0 -and (Test-GlobalSourceRegistration -ClaudeDir $ClaudeDir -PluginName $PluginName -Repo $Repo)) {
        Write-Ok "GitHub-источник зарегистрирован глобально со второй попытки"
    }
    else {
        Write-Err "Claude Code не зарегистрировал глобальный источник плагина"
        Write-Err "Ожидаемый файл: $(Join-Path $ClaudeDir 'plugins/known_marketplaces.json')"
        Write-Err "Попробуй выполнить вручную:"
        Write-Err "  claude plugin marketplace remove $PluginName --scope user"
        Write-Err "  claude plugin marketplace add $Repo --scope user"
        exit 1
    }
}

Update-UserMarketplace -PluginName $PluginName

# -- 2. Install the plugin --------------------------------------------------

Write-Info "Устанавливаю плагин..."

$installResult = & claude plugin install $pluginKey --scope user 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Плагин установлен и включён"
}
else {
    Write-Err "Не удалось установить плагин"
    Write-Err "Можно установить его вручную:"
    Write-Err "  claude plugin marketplace add $Repo --scope user"
    Write-Err "  claude plugin install $pluginKey --scope user"
    exit 1
}

# -- 3. Patch hooks and MCP with the detected Python -----------------------

$PluginRoot = Get-InstalledPluginRoot -ClaudeDir $ClaudeDir -PluginName $PluginName -Version $Version
$hooksJson = $null
$mcpJson = $null

Write-Info "Используй /alfred-dev:alfred или /alfred-dev:feature. ~/.claude/skills не затрагивается."
Assert-UserScopeInstallation -PluginKey $pluginKey

if ($PluginRoot) {
    $hooksPath = Join-Path $PluginRoot "hooks/hooks.json"
    $mcpPath = Join-Path $PluginRoot ".mcp.json"
    if (Test-Path $hooksPath -PathType Leaf) {
        $hooksJson = Get-Item $hooksPath
    }
    if (Test-Path $mcpPath -PathType Leaf) {
        $mcpJson = Get-Item $mcpPath
    }
}

if ($hooksJson) {
    $hooksData = (Get-Content $hooksJson.FullName -Raw -Encoding UTF8) | ConvertFrom-Json
    $patchedHooks = $false
    $quotedPython = '"' + $Python.ExecutablePath + '" ${CLAUDE_PLUGIN_ROOT}'

    foreach ($eventGroup in $hooksData.hooks.PSObject.Properties) {
        foreach ($matcher in $eventGroup.Value) {
            if (-not $matcher.hooks) { continue }
            foreach ($hook in $matcher.hooks) {
                if ($hook.type -ne 'command' -or -not $hook.command) { continue }
                if ($hook.command -eq 'python3') {
                    $hook.command = $Python.ExecutablePath
                    $patchedHooks = $true
                    continue
                }
                if ($hook.command -match 'python3 \$\{CLAUDE_PLUGIN_ROOT\}') {
                    $hook.command = $hook.command -replace 'python3 \$\{CLAUDE_PLUGIN_ROOT\}', $quotedPython
                    $patchedHooks = $true
                }
            }
        }
    }

    if ($patchedHooks) {
        Write-TextFileAtomic $hooksJson.FullName ($hooksData | ConvertTo-Json -Depth 20)
        Write-Ok "hooks.json пропатчен на $($Python.ExecutablePath)"
    }
}
else {
    Write-Info "Внимание: в активной установке нет hooks.json для патча Python"
}

if ($mcpJson) {
    $mcpData = (Get-Content $mcpJson.FullName -Raw -Encoding UTF8) | ConvertFrom-Json
    $mcpServers = $mcpData
    if ($mcpData.PSObject.Properties.Name.Contains("mcpServers")) {
        $mcpServers = $mcpData.mcpServers
    }
    if ($mcpServers.'alfred-memory'.command -ne $Python.ExecutablePath) {
        $mcpServers.'alfred-memory'.command = $Python.ExecutablePath
        Write-TextFileAtomic $mcpJson.FullName ($mcpData | ConvertTo-Json -Depth 20)
        Write-Ok ".mcp.json пропатчен на $($Python.ExecutablePath)"
    }
}
else {
    Write-Info "Внимание: в активной установке нет .mcp.json для патча Python"
}

# -- Result ----------------------------------------------------------------

Write-Host ""
Write-Host "Установка завершена" -ForegroundColor Green
Write-Host ""
Write-Host "  В Claude Code выполни /reload-plugins, а затем:"
Write-Host "  /alfred-dev:alfred" -ForegroundColor White
Write-Host "  Статус: /alfred-dev:progress · продолжить: /alfred-dev:resume" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Если /reload-plugins предупреждает о MCP/стоимости cache или плагин не появился, перезапусти Claude Code." -ForegroundColor DarkGray
Write-Host "  Репозиторий: https://github.com/$Repo" -ForegroundColor DarkGray
Write-Host "  Документация: https://alfred-dev.com" -ForegroundColor DarkGray
Write-Host ""
