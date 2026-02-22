<#
.SYNOPSIS
    Converts images to WEBP sequentially into date-based directories.

.DESCRIPTION
    Looks at an input directory, runs multiple parallel imagemagick conversions on the 
    files there (png, gif, jpg, jpeg), and pushes them into target directories 
    based on the current date and the number of existing files in the folders.
    If no input directory is specified, it defaults to './input'.

.PARAMETER InputDir
    The path to the input directory. Defaults to './input'.

.EXAMPLE
    .\sequential-images.ps1 -InputDir .\my_images
#>
[CmdletBinding()]
param (
    [string]$InputDir = ".\input"
)
$ErrorActionPreference = "Stop"

$MaxFilesPerDir = 150
$BaseDir = "."

# Find output dir logic
$today = Get-Date
$year = $today.Year
$month = "{0:D2}" -f $today.Month

$suffix = 1
$OutputDir = ""
$StartNum = 1

while ($true) {
    $dirSuffix = "{0:D2}" -f $suffix
    $dirName = Join-Path $BaseDir "$year-$month-$dirSuffix"

    if (-not (Test-Path $dirName)) {
        New-Item -ItemType Directory -Path $dirName | Out-Null
        $OutputDir = $dirName
        $StartNum = 1
        break
    }

    $existingFilesCount = @(Get-ChildItem -Path $dirName -Filter "img-*.webp" -File).Count
    if ($existingFilesCount -lt $MaxFilesPerDir) {
        $OutputDir = $dirName
        $StartNum = $existingFilesCount + 1
        break
    }

    $suffix++
}

# Ensure the Input Directory exists before searching
if (-not (Test-Path $InputDir)) {
    Write-Host "Input directory '$InputDir' does not exist." -ForegroundColor Yellow
    exit 0
}

# Find valid input files
$extensions = @('.png', '.gif', '.jpg', '.jpeg')
$inputFiles = Get-ChildItem -Path $InputDir -File | Where-Object Extension -in $extensions | Sort-Object Name

if ($null -eq $inputFiles -or @($inputFiles).Count -eq 0) {
    Write-Host "No PNG, GIF, JPG, or JPEG files found in '$InputDir'"
    exit 0
}

# Prepare jobs
$num = $StartNum
$jobs = foreach ($file in $inputFiles) {
    $destName = "img-{0:D4}.webp" -f $num
    $destPath = Join-Path $OutputDir $destName
    Write-Host "$($file.FullName) => $destPath"
    
    [PSCustomObject]@{
        Src = $file.FullName
        Dest = $destPath
    }
    $num++
}

# Worker pool executing conversions in parallel
$results = $jobs | ForEach-Object -Parallel {
    $success = $true
    $msg = ""
    try {
        & magick $_.Src "-quality" "75" $_.Dest
        if ($LASTEXITCODE -ne 0) {
            $success = $false
            $msg = "imagemagick failed on $($_.Src) (exit status $LASTEXITCODE)"
        }
    } catch {
        $success = $false
        $msg = "imagemagick failed on $($_.Src): $_"
    }

    [PSCustomObject]@{
        Src = $_.Src
        Success = $success
        Message = $msg
    }
} -ThrottleLimit 6

# Check for errors
$failedRuns = @($results | Where-Object { -not $_.Success })

if ($failedRuns.Count -gt 0) {
    foreach ($err in $failedRuns) {
        Write-Error "Conversion error: $($err.Message)"
    }
    Write-Error "Conversion(s) failed!"
    exit 1
}

Write-Host "Successfully converted $(@($jobs).Count) files to $OutputDir"
