// SPDX-License-Identifier: MIT
package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"sync"
	"time"
)

const (
	maxFilesPerDir    = 150
	baseDir           = "."
	inputDir          = "input"
	maxConcurrentJobs = 4
)

type job struct {
	src  string
	dest string
}

// findOutputDir finds the correct output directory exactly like the Ruby version:
// - Uses today's date
// - Tries suffixes 01, 02, ... until it finds a dir with <150 files or creates a new one
func findOutputDir() (string, int, error) {
	today := time.Now()
	year := today.Year()
	month := today.Format("01") // zero-padded

	suffix := 1
	for {
		dirSuffix := fmt.Sprintf("%02d", suffix)
		dirName := filepath.Join(baseDir, fmt.Sprintf("%d-%s-%s", year, month, dirSuffix))

		if _, err := os.Stat(dirName); os.IsNotExist(err) {
			// Directory doesn't exist → create and use it
			if err := os.MkdirAll(dirName, 0755); err != nil {
				return "", 0, fmt.Errorf("failed to create %s: %w", dirName, err)
			}
			return dirName, 1, nil
		}

		// Count existing img-*.webp files
		matches, err := filepath.Glob(filepath.Join(dirName, "img-*.webp"))
		if err != nil {
			return "", 0, fmt.Errorf("glob failed in %s: %w", dirName, err)
		}

		if len(matches) < maxFilesPerDir {
			// Room left → use this directory
			return dirName, len(matches) + 1, nil
		}

		// Full → try next suffix
		suffix++
	}
}

func main() {
	// Find the single output directory for this entire batch
	outputDir, startNum, err := findOutputDir()
	if err != nil {
		log.Fatalf("Error determining output directory: %v", err)
	}

	// Get and sort input PNG files
	inputPattern := filepath.Join(inputDir, "*.png")
	pngFiles, err := filepath.Glob(inputPattern)
	if err != nil {
		log.Fatalf("Failed to read input directory: %v", err)
	}
	if len(pngFiles) == 0 {
		fmt.Println("No PNG files found in './input'")
		return
	}
	slices.Sort(pngFiles)

	// Prepare all jobs (sequential numbering in the chosen directory)
	jobs := make([]job, len(pngFiles))
	num := startNum
	for i, src := range pngFiles {
		dest := filepath.Join(outputDir, fmt.Sprintf("img-%04d.webp", num))
		jobs[i] = job{src: src, dest: dest}
		fmt.Printf("%s => %s\n", src, dest)
		num++
	}

	// Worker pool: up to 4 concurrent conversions
	jobChan := make(chan job, maxConcurrentJobs)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var errList []error

	for i := 0; i < maxConcurrentJobs; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range jobChan {
				cmd := exec.Command("magick", j.src, "-quality", "75", j.dest)
				if err := cmd.Run(); err != nil {
					mu.Lock()
						if exitErr, ok := err.(*exec.ExitError); ok {
							errList = append(errList,fmt.Errorf("imagemagick failed on %s (exit status %d)", j.src, exitErr.ExitCode()))
						} else {
							errList = append(errList, fmt.Errorf("imagemagick failed on %s: %w", j.src, err))
						}
					mu.Unlock()
				}
			}
		}()
	}

	// Send jobs
	for _, j := range jobs {
		jobChan <- j
	}
	close(jobChan)

	wg.Wait()

	if len(errList) != 0 {
		for _, e := range errList {
			log.Printf("Conversion error: %v\n", e)
		}
		log.Fatalln("Conversion(s) failed!")
	}

	fmt.Printf("Successfully converted %d files to %s\n", len(jobs), outputDir)
}
