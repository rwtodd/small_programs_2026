package main

// SPDX-License-Identifier: MIT

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
)

func main() {
	if len(os.Args) < 2 || os.Args[1] == "--help" {
		fmt.Println("usage: zip-to-aac path/to/album.zip")
		os.Exit(1)
	}
	zipFile := os.Args[1]

	base := strings.TrimSuffix(filepath.Base(zipFile), ".zip")
	outputDir := base
	err := os.MkdirAll(outputDir, 0755)
	if err != nil {
		panic(err)
	}

	tempDir, err := os.MkdirTemp("", "zip_extract_")
	if err != nil {
		panic(err)
	}
	defer os.RemoveAll(tempDir)
	//fmt.Println("Temp dir: ", tempDir)

	// Unzip the file
	r, err := zip.OpenReader(zipFile)
	if err != nil {
		panic(err)
	}
	defer r.Close()

	var coverPath string
	musicFiles := []string{}
	for _, f := range r.File {
		if f.FileInfo().IsDir() {
			continue
		}
		ext := strings.ToLower(filepath.Ext(f.Name))
		targetPath := filepath.Join(tempDir, f.Name)
		err = os.MkdirAll(filepath.Dir(targetPath), 0755)
		if err != nil {
			panic(err)
		}
		outF, err := os.Create(targetPath)
		if err != nil {
			panic(err)
		}
		inF, err := f.Open()
		if err != nil {
			panic(err)
		}
		_, err = io.Copy(outF, inF)
		if err != nil {
			panic(err)
		}
		outF.Close()
		inF.Close()

		switch ext {
		case ".jpg", ".jpeg":
			if coverPath == "" || strings.HasPrefix(f.Name, "cover") || strings.HasPrefix(f.Name, "Cover") {
				coverPath = targetPath
			}
		case ".flac", ".m4a", ".mp3", ".ogg":
			musicFiles = append(musicFiles, targetPath)
		}
	}

	if coverPath == "" {
		fmt.Println("Warning: No cover art found in ZIP. Proceeding without embedding cover where necessary.")
	}

	// Process music files concurrently
	var wg sync.WaitGroup
	sem := make(chan struct{}, 8) // Limit to 8 concurrent ffmpeg runs
	for _, input := range musicFiles {
		wg.Add(1)
		go func(input string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			processFile(input, coverPath, outputDir)
		}(input)
	}
	wg.Wait()
}

func processFile(input, cover, outputDir string) {
	filename := filepath.Base(input)
	ext := strings.ToLower(filepath.Ext(filename))
	baseName := strings.TrimSuffix(filename, ext)
	outputFile := ""
	codec := getCodec(input)
	hasCover := getHasCover(input)
	isMP3 := ext == ".mp3" && codec == "mp3"
	isAAC := ext == ".m4a" && codec == "aac"

	if isMP3 || isAAC {
		outputFile = filepath.Join(outputDir, filename)
		if hasCover || cover == "" {
			// Copy as-is if has cover or no cover available
			err := copyFile(input, outputFile)
			if err != nil {
				fmt.Printf("Error copying %s: %v\n", filename, err)
			}
		} else {
			// Embed cover
			err := embedCover(input, cover, outputFile, isMP3)
			if err != nil {
				fmt.Printf("Error embedding cover in %s: %v\n", filename, err)
			}
		}
	} else {
		// Convert to AAC
		outputFile = filepath.Join(outputDir, baseName+".m4a")
		if cover == "" {
			// Convert without cover
			err := convertFileWithoutCover(input, outputFile)
			if err != nil {
				fmt.Printf("Error converting %s without cover: %v\n", filename, err)
			}
		} else {
			err := convertFile(input, cover, outputFile)
			if err != nil {
				fmt.Printf("Error converting %s: %v\n", filename, err)
			}
		}
	}
}

func getCodec(input string) string {
	cmd := exec.Command("ffprobe", "-v", "quiet", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", input)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

type FFProbe struct {
	Streams []struct {
		CodecType   string `json:"codec_type"`
		Disposition struct {
			AttachedPic int `json:"attached_pic"`
		} `json:"disposition"`
	} `json:"streams"`
}

func getHasCover(input string) bool {
	cmd := exec.Command("ffprobe", "-v", "quiet", "-show_format", "-show_streams", "-print_format", "json", input)
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	var probe FFProbe
	err = json.Unmarshal(out, &probe)
	if err != nil {
		return false
	}
	for _, s := range probe.Streams {
		if s.CodecType == "video" && s.Disposition.AttachedPic == 1 {
			return true
		}
	}
	return false
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

func embedCover(input, cover, output string, isMP3 bool) error {
	args := []string{
		"-i", input,
		"-i", cover,
		"-map", "0",
		"-map", "-0:v",
		"-map", "1:v",
		"-c", "copy",
		"-map_metadata", "0",
		"-disposition:v", "attached_pic",
	}
	if isMP3 {
		args = append(args, "-id3v2_version", "3")
	} else {
		args = append(args, "-movflags", "+faststart")
	}
	args = append(args, output)
	cmd := exec.Command("ffmpeg", args...)
	cmdoutput, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("Error encoding track %s:\n%s\nError: %v", input, string(cmdoutput), err)
	}
	return nil
}

func convertFile(input, cover, output string) error {
	args := []string{
		"-i", input,
		"-i", cover,
		"-map", "0:a:0",
		"-map", "1:v:0",
		"-map_metadata", "0",
		"-id3v2_version", "3",
		"-af", "aresample=resampler=soxr:precision=33:osr=44100",
		"-c:a", "aac_at",
		"-aac_at_mode", "cvbr",
		"-b:a", "256k",
		"-c:v", "copy",
		"-disposition:v:0", "attached_pic",
		"-movflags", "+faststart",
		output,
	}
	cmd := exec.Command("ffmpeg", args...)
	cmdoutput, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("Error encoding track %s:\n%s\nError: %v", input, string(cmdoutput), err)
	}
	return nil
}

func convertFileWithoutCover(input, output string) error {
	args := []string{
		"-i", input,
		"-map", "0:a:0",
		"-map_metadata", "0",
		"-id3v2_version", "3",
		"-af", "aresample=resampler=soxr:precision=33:osr=44100",
		"-c:a", "aac_at",
		"-aac_at_mode", "cvbr",
		"-b:a", "256k",
		"-movflags", "+faststart",
		output,
	}
	cmd := exec.Command("ffmpeg", args...)
	cmdoutput, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("Error encoding track %s:\n%s\nError: %v", input, string(cmdoutput), err)
	}
	return nil
}
