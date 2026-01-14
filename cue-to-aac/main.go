package main

// SPDX-License-Identifier: MIT

import (
	"bufio"
	"fmt"
	"log"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
)

const maxConcurrency = 8

type Track struct {
	Number string
	Title  string
	Artist string
	Start  string
}

func main() {
	if len(os.Args) < 4 {
		fmt.Println("Usage: cue-to-aac <file.cue> <file.flac> <cover.jpg>")
		return
	}

	cueFile, flacFile, coverFile := os.Args[1], os.Args[2], os.Args[3]
	album, _, tracks := parseCue(cueFile)

	var wg sync.WaitGroup
	sem := make(chan struct{}, maxConcurrency)
	for i, t := range tracks {
		// Calculate duration for all but the last track
		durationFlag := []string{}
		if i < len(tracks)-1 {
			nextStart, _ := strconv.ParseFloat(tracks[i+1].Start, 64)
			currentStart, _ := strconv.ParseFloat(t.Start, 64)
			duration := nextStart - currentStart
			durationFlag = append(durationFlag, "-t", fmt.Sprintf("%f", duration))
		}

		wg.Add(1)
		go func(t Track, dFlag []string) {
			sem <- struct{}{}

			// 3. "Release" the slot when the function finishes
			defer func() {
				<-sem
				wg.Done()
			}()

			// Sanitize the filename but keep the metadata original
			cleanTitle := sanitize(t.Title)
			outputName := fmt.Sprintf("%s_%s.m4a", t.Number, cleanTitle)

			args := []string{
				"-hide_banner",
				"-loglevel", "error",
				"-ss", t.Start,
			}
			args = append(args, dFlag...)
			args = append(args,
				"-i", flacFile,
				"-i", coverFile,
				"-map", "0:a:0", // Map the audio from the first file
				"-map", "1:v:0", // Map the video/image from the second file
				"-c:a", "aac_at",
				"-aac_at_mode", "cvbr",
				"-b:a", "256k",
				"-ar", "44100",
				"-c:v", "copy", // CRITICAL: Don't re-encode the JPEG; keep it as mjpeg
				"-disposition:v:0", "attached_pic", // Tell the container this is cover art
				"-metadata", "track="+t.Number,
				"-metadata", "title="+t.Title,
				"-metadata", "artist="+t.Artist,
				"-metadata", "album="+album,
				outputName,
			)

			cmd := exec.Command("ffmpeg", args...)
			output, err := cmd.CombinedOutput()
			if err != nil {
				log.Printf("Error encoding track %s:\n%s\nError: %v", t.Number, string(output), err)
			} else {
				fmt.Printf("Successfully created: %s\n", outputName)
			}
		}(t, durationFlag)
	}
	wg.Wait()
	fmt.Println("All tracks processed.")
}

// sanitize handles the filename clamping logic
func sanitize(s string) string {
	// 1. Replace anything not 0-9, a-z, or A-Z with an underscore
	// 2. The '+' in the regex automatically collapses multiple non-alnum chars into one underscore
	reg := regexp.MustCompile(`[^a-zA-Z0-9]+`)
	safe := reg.ReplaceAllString(s, "_")

	// Trim leading/trailing underscores for a cleaner look
	return strings.Trim(safe, "_")
}

func parseCue(filename string) (string, string, []Track) {
	file, err := os.Open(filename)
	if err != nil {
		log.Fatalf("Failed to open CUE: %v", err)
	}
	defer file.Close()

	var tracks []Track
	var album, globalArtist string
	var currentTrack *Track

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "TITLE") && currentTrack == nil {
			album = strings.Trim(line[6:], "\"")
		} else if strings.HasPrefix(line, "PERFORMER") {
			val := strings.Trim(line[10:], "\"")
			if currentTrack == nil {
				globalArtist = val
			} else {
				currentTrack.Artist = val
			}
		} else if strings.HasPrefix(line, "TRACK") {
			if currentTrack != nil {
				tracks = append(tracks, *currentTrack)
			}
			// Extract track number (e.g., TRACK 01 AUDIO -> 01)
			numParts := strings.Fields(line)
			currentTrack = &Track{Number: numParts[1], Artist: globalArtist}
		} else if currentTrack != nil {
			if strings.HasPrefix(line, "TITLE") {
				currentTrack.Title = strings.Trim(line[6:], "\"")
			} else if strings.HasPrefix(line, "INDEX 01") {
				currentTrack.Start = cueTimeToSeconds(line[9:])
			}
		}
	}
	if currentTrack != nil {
		tracks = append(tracks, *currentTrack)
	}
	return album, globalArtist, tracks
}

func cueTimeToSeconds(cueTime string) string {
	parts := strings.Split(cueTime, ":")
	if len(parts) != 3 {
		return "0"
	}
	min, _ := strconv.ParseFloat(parts[0], 64)
	sec, _ := strconv.ParseFloat(parts[1], 64)
	frames, _ := strconv.ParseFloat(parts[2], 64)
	return fmt.Sprintf("%f", (min*60)+sec+(frames/75.0))
}
