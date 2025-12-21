package main

import (
	"bytes"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"

	"github.com/rwtodd/Go.Epub3/epub"
)

// result holds the processed image data to be added to the EPUB in order
type result struct {
	Index   int
	Content []byte
	Ext     string
	Width   int
	Height  int
	Err     error
}

func main() {
	// 1. Command line arguments
	title := flag.String("title", "My eBook", "EPUB title")
	publisher := flag.String("publisher", "Unknown", "EPUB publisher")
	year := flag.Int("year", 1977, "Publication year")
	quality := flag.Int("quality", 80, "Webp conversion quality")
	excludePattern := flag.String("exclude", "", "Regex pattern to exclude filenames (e.g. '^zz')")
	baseName := flag.String("imgbase", "page", "Base name for images inside EPUB")
	flag.Parse()

	if flag.NArg() != 1 {
		flag.Usage()
		log.Fatalln("Must give an input file (.cbr/.cbz)!")
	}
	inputFile := flag.Args()[0]

	// Pre-compile regex if provided
	var excludeRegex *regexp.Regexp
	if *excludePattern != "" {
		var err error
		excludeRegex, err = regexp.Compile(*excludePattern)
		if err != nil {
			log.Fatalf("Invalid regex pattern: %v", err)
		}
	}

	tempDir := "out_tmp"

	// 2. Prepare temp directory
	os.RemoveAll(tempDir)
	if err := os.MkdirAll(tempDir, 0755); err != nil {
		log.Fatalf("Failed to create temp dir: %v", err)
	}

	// 3. Extract archive
	cmd7z := exec.Command("7zz", "e", "-o"+tempDir, inputFile)
	if err := cmd7z.Run(); err != nil {
		log.Fatalf("7zz failed: %v", err)
	}

	// 4. Find and sort JPEGs
	files, _ := filepath.Glob(filepath.Join(tempDir, "*"))
	var jpegs []string
	for _, f := range files {

		// Apply Regex Exclusion
		if excludeRegex != nil {
			fileName := filepath.Base(f)
			if excludeRegex.MatchString(fileName) {
				continue
			}
		}

		ext := strings.ToLower(filepath.Ext(f))
		if ext == ".jpg" || ext == ".jpeg" {
			jpegs = append(jpegs, f)
		}
	}
	sort.Strings(jpegs)

	if len(jpegs) == 0 {
		log.Fatal("No JPEG files found in archive.")
	}

	// 5. Concurrent Processing
	numJpegs := len(jpegs)
	results := make([]*result, numJpegs)
	var wg sync.WaitGroup
	semaphore := make(chan struct{}, 5) // Limit to 5 parallel magick processes

	for i, path := range jpegs {
		wg.Add(1)
		go func(index int, filePath string) {
			defer wg.Done()
			semaphore <- struct{}{}        // Acquire
			defer func() { <-semaphore }() // Release

			results[index] = processImage(index, *quality, filePath)
		}(i, path)
	}
	wg.Wait()

	// 6. Assemble EPUB
	outputFilename := strings.ReplaceAll(*title, " ", "_") + ".epub"
	e, err := epub.NewEpubWriter(outputFilename, *title, *publisher, *year)
	if err != nil {
		log.Fatalf("couldn't create output epub! %v", err)
	}
	defer func() {
		if err := e.Close(); err != nil {
			log.Fatalf("Could not write epub! %v", err)
		}
	}()

	for i, res := range results {
		if res.Err != nil {
			log.Printf("Error processing image %d: %v", i, res.Err)
			continue
		}

		// Generate filename: base001.webp or base001.jpg
		internalImgName := fmt.Sprintf("%s-%03d%s", *baseName, i+1, res.Ext)

		// Add image to EPUB
		err = e.AddDimensionedImageFile(internalImgName, res.Content, i == 0, res.Width, res.Height)
		if err != nil {
			log.Fatalf("Failed to add image to EPUB: %v", err)
		}

		// Create full-page image section
		internalXmlName := fmt.Sprintf("%s-%03d%s", *baseName, i+1, ".xhtml")
		err = e.AddFullpagePic(internalXmlName, internalImgName)
		if err != nil {
			log.Printf("Failed to add page to EPUB: %v", err)
		}
	}
}

func processImage(index, quality int, path string) *result {
	// 4.a Read all bytes
	jpgData, err := os.ReadFile(path)
	if err != nil {
		return &result{Err: err}
	}

	// 4.b Run magick
	// magick jpeg:- -format '%w %h\n' -write info:fd:2 -quality 75% webp:-
	qualityStr := fmt.Sprintf("%d%%", quality)
	cmd := exec.Command("magick", "jpeg:-", "-format", "%w %h\n", "-write", "info:fd:2", "-quality", qualityStr, "webp:-")
	cmd.Stdin = bytes.NewReader(jpgData)

	var stdoutBuf, stderrBuf bytes.Buffer
	cmd.Stdout = &stdoutBuf
	cmd.Stderr = &stderrBuf

	if err := cmd.Run(); err != nil {
		return &result{Err: fmt.Errorf("magick failed: %v, stderr: %s", err, stderrBuf.String())}
	}

	// Parse dimensions from stderr
	var w, h int
	fmt.Sscanf(stderrBuf.String(), "%d %d", &w, &h)

	webpData := stdoutBuf.Bytes()

	// 4.c Size comparison
	if len(webpData) < len(jpgData) {
		return &result{Index: index, Content: webpData, Ext: ".webp", Width: w, Height: h}
	}
	return &result{Index: index, Content: jpgData, Ext: ".jpg", Width: w, Height: h}
}
