param([string]$Store = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

function Wait-IfStandalone {
    if ($env:VIDEO_IMPORT_NO_PAUSE) { return }
    try {
        $parentId = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
        $parent = (Get-Process -Id $parentId -ErrorAction Stop).ProcessName
    } catch { return }
    if ($parent -notin @('explorer', 'sihost', 'RuntimeBroker')) { return }
    Write-Host ''
    Read-Host '按 Enter 关闭窗口'
}

function Find-JsonArrayEnd([string]$Text, [int]$Open) {
    $inString = $false
    $escape = $false
    $depth = 0
    for ($i = $Open; $i -lt $Text.Length; $i++) {
        $ch = $Text[$i]
        if ($inString) {
            if ($escape) { $escape = $false }
            elseif ($ch -eq [char]92) { $escape = $true }
            elseif ($ch -eq '"') { $inString = $false }
            continue
        }
        if ($ch -eq '"') { $inString = $true; continue }
        if ($ch -eq '[') { $depth++ }
        elseif ($ch -eq ']') {
            $depth--
            if ($depth -eq 0) { return $i }
        }
    }
    return -1
}

function Add-DraftStoreEntry([string]$IndexText, [string]$EntryJson) {
    $token = '"all_draft_store"'
    $key = $IndexText.IndexOf($token)
    if ($key -lt 0) { throw '无法识别剪映草稿索引，未做任何修改。' }
    $colon = $IndexText.IndexOf(':', $key + $token.Length)
    if ($colon -lt 0) { throw '无法识别剪映草稿索引，未做任何修改。' }
    $open = $IndexText.IndexOf('[', $colon)
    if ($open -lt 0) { throw '无法识别剪映草稿索引，未做任何修改。' }
    $close = Find-JsonArrayEnd $IndexText $open
    if ($close -lt 0) { throw '无法识别剪映草稿索引，未做任何修改。' }
    $inside = $IndexText.Substring($open + 1, $close - $open - 1).Trim()
    $inserted = if ($inside) { $inside.TrimEnd() + ',' + $EntryJson } else { $EntryJson }
    return $IndexText.Substring(0, $open + 1) + $inserted + $IndexText.Substring($close)
}

$lock = $null
$copied = $false
$registered = $false
$destination = $null
try {
    $packageRoot = [IO.Path]::GetFullPath($(if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Path $MyInvocation.MyCommand.Path -Parent }))
    $sourceDraft = Join-Path $packageRoot 'draft'
    $manifestPath = Join-Path $packageRoot 'manifest.json'
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw '请先把 ZIP 完整解压到文件夹，再运行 Import-Draft.ps1。' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Store) { $Store = Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft' }
    $Store = [IO.Path]::GetFullPath($Store)
    $indexPath = Join-Path $Store 'root_meta_info.json'
    $draftContent = Get-Content -LiteralPath (Join-Path $sourceDraft 'draft_content.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $folderName = 'workbench-' + $manifest.draft_id
    if ($folderName -notmatch '^workbench-[a-zA-Z0-9-]+$') { throw '草稿编号无效。' }
    $destination = [IO.Path]::GetFullPath((Join-Path $Store $folderName))
    if (-not $destination.StartsWith($Store.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '导入路径无效。' }
    if (Test-Path -LiteralPath $destination) {
        Write-Host "这份草稿已经导入过，不会覆盖。"
        Write-Host "请打开剪映，在首页查找：$($draftContent.name)"
        return
    }

    $jyFontRoot = Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Resources\Font'
    $jyEffectRoot = Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Cache\effect'
    foreach ($resource in $manifest.native_resources) {
        $resourceRoot = if ($resource.kind -eq 'font') { $jyFontRoot } else { $jyEffectRoot }
        $resourceRoot = [IO.Path]::GetFullPath($resourceRoot)
        $resourcePath = [IO.Path]::GetFullPath((Join-Path $resourceRoot $resource.relative_path))
        if (-not $resourcePath.StartsWith($resourceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '资源路径无效。' }
        if (-not (Test-Path -LiteralPath $resourcePath)) { throw "剪映缺少资源：$($resource.name)。请先在剪映中下载该字体或文字动画，再重试。" }
    }
    foreach ($entry in $manifest.files.PSObject.Properties) {
        if ($entry.Name -in @('Import-Draft.ps1', '使用说明.txt')) { continue }
        $relative = $entry.Name.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $itemPath = [IO.Path]::GetFullPath([IO.Path]::Combine($packageRoot, $relative))
        if (-not $itemPath.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw '压缩包包含无效路径。'
        }
        if (-not (Test-Path -LiteralPath $itemPath)) { throw "文件缺失：$($entry.Name)。请重新解压完整 ZIP。" }
        if ((Get-FileHash -LiteralPath $itemPath -Algorithm SHA256).Hash.ToLower() -ne $entry.Value) {
            throw "文件校验失败：$($entry.Name)。请重新下载并完整解压。"
        }
    }
    if (-not (Test-Path -LiteralPath $indexPath)) { throw "找不到剪映草稿库：$Store。请先打开一次剪映，或使用 -Store 指定草稿目录。" }
    if (Get-Process -Name 'JianyingPro','CapCut' -ErrorAction SilentlyContinue) {
        throw '请先保存并退出剪映，再导入。'
    }

    $lock = [IO.File]::Open((Join-Path $Store '.video-workbench-import.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $indexBytes = [IO.File]::ReadAllBytes($indexPath)
    $originalHash = (Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash
    $indexText = $utf8.GetString($indexBytes).TrimStart([char]0xFEFF)
    if ($indexText -notmatch '"all_draft_store"') { throw '无法识别剪映草稿索引，未做任何修改。' }
    if ($indexText -match ('"draft_id"\s*:\s*"' + [regex]::Escape([string]$manifest.draft_id) + '"')) {
        throw '这份草稿已经在剪映首页中，不会覆盖。请打开剪映查找。'
    }
    Copy-Item -LiteralPath $sourceDraft -Destination $destination -Recurse
    $copied = $true
    $draftEscaped = (ConvertTo-Json -InputObject $destination.Replace('\','/') -Compress).Trim('"')
    $storeEscaped = (ConvertTo-Json -InputObject $Store.Replace('\','/') -Compress).Trim('"')
    $fontEscaped = (ConvertTo-Json -InputObject $jyFontRoot.Replace('\','/') -Compress).Trim('"')
    $effectEscaped = (ConvertTo-Json -InputObject $jyEffectRoot.Replace('\','/') -Compress).Trim('"')
    Get-ChildItem -LiteralPath $destination -Recurse -File | Where-Object { $_.Extension -eq '.json' -or $_.Name -eq 'template-2.tmp' } | ForEach-Object {
        $raw = [IO.File]::ReadAllText($_.FullName, $utf8)
        $raw = $raw.Replace('__DRAFT_ROOT__', $draftEscaped).Replace('__STORE_ROOT__', $storeEscaped)
        $raw = $raw.Replace('__JY_FONT_ROOT__', $fontEscaped).Replace('__JY_EFFECT_ROOT__', $effectEscaped)
        $null = $raw | ConvertFrom-Json
        [IO.File]::WriteAllText($_.FullName, $raw, $utf8)
    }
    $metaPath = Join-Path $destination 'draft_meta_info.json'
    $metaJson = [IO.File]::ReadAllText($metaPath, $utf8)
    $nameJson = ConvertTo-Json -InputObject ([string]$draftContent.name) -Compress
    $metaJson = [regex]::Replace($metaJson, '"draft_name"\s*:\s*".*?"', '"draft_name":' + $nameJson, 1)
    $null = $metaJson | ConvertFrom-Json
    [IO.File]::WriteAllText($metaPath, $metaJson, $utf8)
    if ((Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash -ne $originalHash) { throw '导入过程中草稿索引被其它程序改动，未完成登记。请关闭剪映后联系管理员。' }
    $nextIndex = Add-DraftStoreEntry $indexText $metaJson
    $tempIndex = Join-Path $Store ('root_meta_info.workbench-' + [guid]::NewGuid().ToString() + '.tmp')
    [IO.File]::WriteAllText($tempIndex, $nextIndex, $utf8)
    $backup = Join-Path $Store ('root_meta_info.before-workbench-' + [DateTime]::Now.ToString('yyyyMMddHHmmssfff') + '.json')
    [IO.File]::Replace($tempIndex, $indexPath, $backup)
    $registered = $true
    Write-Host "已导入：$($draftContent.name)"
    Write-Host '请打开剪映，在首页找到该草稿后检查并导出。'
} catch {
    if ($copied -and -not $registered -and $destination -and (Test-Path -LiteralPath $destination)) {
        Remove-Item -LiteralPath $destination -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host ('导入失败：' + $_.Exception.Message)
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
    Wait-IfStandalone
}
