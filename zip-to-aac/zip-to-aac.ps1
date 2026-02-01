<#
.SYNOPSIS
    Extracts a ZIP archive and converts contained audio files to AAC/M4A.

.DESCRIPTION
    This script automates the extraction of music from a ZIP file and ensures all tracks are in a 
    standardized AAC format (m4a). It replicates the logic of the Go zip-to-aac tool:
    1. Extracts the ZIP to a temporary directory.
    2. Identifies cover art (prioritizing files starting with 'cover').
    3. Identifies audio files (.flac, .mp3, .m4a, .ogg).
    4. Probes codecs: Copies MP3/AAC as-is (embedding cover if missing), or converts other 
       formats to AAC using the Apple 'aac_at' encoder.
    5. Processes files in parallel for performance.

.PARAMETER ZipPath
    The literal path to the ZIP file containing the album tracks and cover art.

.EXAMPLE
    .\zip-to-aac.ps1 -ZipPath "C:\Downloads\NewAlbum.zip"
    Extracts NewAlbum.zip and creates a folder named 'NewAlbum' with converted tracks.

.NOTES
    Requires ffmpeg (with aac_at support) and ffprobe to be available in the system PATH.
#>
param (
    [Parameter(Mandatory=$true, Position=0, HelpMessage="Path to the source ZIP file")]
    [string]$ZipPath
)

if (-not (Test-Path $ZipPath)) {
    Write-Error "File not found: $ZipPath"
    exit 1
}

# Setup output and temp paths based on input filename
$baseName = [System.IO.Path]::GetFileNameWithoutExtension($ZipPath)
$outputDir = Join-Path (Get-Location) $baseName
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString())

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    Write-Host "Extracting $ZipPath..."
    Expand-Archive -Path $ZipPath -DestinationPath $tempDir -Force

    # Identify files and prioritize cover art
    $allFiles = Get-ChildItem -Path $tempDir -Recurse -File
    $coverFile = $allFiles | Where-Object { $_.Extension -match '\.jpe?g$' } | Sort-Object { 
        if ($_.Name -match '^cover') { 0 } else { 1 } 
    } | Select-Object -First 1

    $coverPath = $coverFile ? $coverFile.FullName : $null
    if (-not $coverPath) {
        Write-Warning "No cover art found in ZIP. Proceeding without embedding."
    }

    # Concurrent processing using PowerShell 7's Parallel feature
    $allFiles | Where-Object { $_.Extension -match '\.(flac|m4a|mp3|ogg)$' } | ForEach-Object -Parallel {
        $inputPath = $_.FullName
        $fileName = $_.Name
        $ext = $_.Extension.ToLower()
        $base = [System.IO.Path]::GetFileNameWithoutExtension($fileName)
        $outputDir = $using:outputDir
        $cover = $using:coverPath

        # Probe file for codec and cover presence using ffprobe
        $probeRaw = ffprobe -v quiet -show_streams -print_format json $inputPath | ConvertFrom-Json
        $audioStream = $probeRaw.streams | Where-Object { $_.codec_type -eq "audio" } | Select-Object -First 1
        $codec = $audioStream.codec_name
        
        $hasCover = $probeRaw.streams | Where-Object { 
            $_.codec_type -eq "video" -and $_.disposition.attached_pic -eq 1 
        }

        $isMP3 = ($ext -eq ".mp3" -and $codec -eq "mp3")
        $isAAC = ($ext -eq ".m4a" -and $codec -eq "aac")

        if ($isMP3 -or $isAAC) {
            $targetPath = Join-Path $outputDir $fileName
            if ($hasCover -or -not $cover) {
                # Copy existing MP3/AAC as-is
                Copy-Item -Path $inputPath -Destination $targetPath -Force
            } else {
                # Embed missing cover into existing MP3/AAC
                $args = @("-i", $inputPath, "-i", $cover, "-map", "0", "-map", "-0:v", "-map", "1:v", "-c", "copy", "-map_metadata", "0", "-disposition:v", "attached_pic")
                if ($isMP3) { $args += @("-id3v2_version", "3") } else { $args += @("-movflags", "+faststart") }
                $args += $targetPath
                & ffmpeg -v error -y @args
            }
        } else {
            # Convert to AAC using specific audio quality flags
            $targetPath = Join-Path $outputDir "$base.m4a"
            $args = @("-i", $inputPath)
            
            if ($cover) {
                $args += @("-i", $cover, "-map", "0:a:0", "-map", "1:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic")
            } else {
                $args += @("-map", "0:a:0")
            }

            $args += @(
                "-map_metadata", "0",
                "-id3v2_version", "3",
                "-af", "aresample=resampler=soxr:precision=33:osr=44100",
                "-c:a", "aac_at",
                "-aac_at_mode", "cvbr",
                "-b:a", "256k",
                "-movflags", "+faststart",
                $targetPath
            )
            & ffmpeg -v error -y @args
        }

        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to process $fileName"
        } else {
            Write-Host "Processed: $fileName"
        }

    } -ThrottleLimit 8

} finally {
    # Cleanup temporary directory
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force
    }
}
