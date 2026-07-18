<#
.SYNOPSIS
    Bulk renames files via pipeline and rules.

.DESCRIPTION
    Takes files from the pipeline and applies renaming rules to the basename (filename without extension).
    Utilizes PowerShell's built-in SupportShouldProcess for -WhatIf and -Confirm functionality.

.PARAMETER Path
    The files to rename. Accepts strings from the pipeline.

.PARAMETER FilterScript
    A scriptblock executed for each file basename. `$_` will be the basename.
    The output of the scriptblock becomes the new basename.

.PARAMETER Alpha
    Replaces non-alphanumeric characters with an underscore.

.PARAMETER Num
    Adds an N-digit incrementing prefix (e.g., 001_, 002_).

.PARAMETER Truncate
    Truncates the basename to a maximum of N characters.

.EXAMPLE
    Get-ChildItem *.mp4 | .\bulk-rename.ps1 { $_ -replace '[-_]+', '_' } -WhatIf
    Renames all .mp4 files in the current folder, replacing runs of hyphens/underscores with a single underscore. Shows what would happen.

.EXAMPLE
    Get-ChildItem *.txt | .\bulk-rename.ps1 -Alpha -Truncate 10 -Num 3 -Confirm
    Truncates basenames to 10 chars, strips formatting, prepends 3 digits, and prompts before each rename.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(ValueFromPipeline = $true, Mandatory = $true, ValueFromPipelineByPropertyName = $true)]
    [Alias('FullName')]
    [string[]]$Path,

    [Parameter(Position = 0)]
    [scriptblock]$FilterScript,

    [switch]$Alpha,

    [int]$Num = 0,

    [int]$Truncate = 0
)

begin {
    $index = 1
    $hasErrors = $false
}

process {
    foreach ($p in $Path) {
        $item = Get-Item -LiteralPath $p -ErrorAction SilentlyContinue
        if (-not $item) {
            Write-Verbose "Item not found: $p"
            continue
        }
        if ($item.PSIsContainer) {
            Write-Verbose "Skipping directory: $p"
            continue
        }

        $ext = $item.Extension
        $name = $item.BaseName

        # 1. Apply ScriptBlock (regexes, etc.)
        try {
            if ($FilterScript) {
                $name = $name | ForEach-Object $FilterScript -ErrorAction Stop
            }
        }
        catch {
            Write-Error "Error in filter script: $_"
            $hasErrors = $true
            continue
        }

        # 2. Alpha Optimization
        if ($Alpha) {
            $name = $name -replace '[^a-zA-Z0-9]+', '_'
            $name = $name.Trim('_')
        }

        # 3. Truncation
        if ($Truncate -gt 0 -and $name.Length -gt $Truncate) {
            $name = $name.Substring(0, $Truncate)
        }

        # 4. Numbering
        if ($Num -gt 0) {
            $name = "{0:D$Num}_{1}" -f $index, $name
            $index++
        }

        $newFileName = $name + $ext

        if ($item.Name -eq $newFileName) {
            Write-Verbose "Skipping: $($item.FullName) (no change)"
            continue
        }

        # Handle ShouldProcess (enables -WhatIf and -Confirm)
        if ($PSCmdlet.ShouldProcess($item.FullName, "Rename to $newFileName")) {
            try {
                Rename-Item -LiteralPath $item.FullName -NewName $newFileName -ErrorAction Stop -Confirm:$false
                Write-Host "Renamed: $($item.FullName) -> $newFileName" -ForegroundColor Green
            }
            catch {
                Write-Error "Error renaming '$($item.FullName)' to '$newFileName': $_"
                $hasErrors = $true
            }
        }
    }
}

end {
    if ($hasErrors) {
        exit 1
    }
}
