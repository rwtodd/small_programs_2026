package main

// SPDX-License-Identifier: MIT

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type Config struct {
	ZeroTerminated bool
	AlphaRegex     *regexp.Regexp
	NumFormat      string
	Truncate       bool
	TruncateLength int
	Yes            bool
	Replacements   []Replacement
}

type Replacement struct {
	Regex       *regexp.Regexp
	Replacement string
}

func main() {
	config := parseArgs()

	scanner := bufio.NewScanner(os.Stdin)
	if config.ZeroTerminated {
		scanner.Split(scanNullTerminated)
	}

	index := 1
	for scanner.Scan() {
		path := scanner.Text()
		if path == "" {
			continue
		}

		dir := filepath.Dir(path)
		filename := filepath.Base(path)

		newFilename := processFilename(filename, index, config)
		index++

		if filename == newFilename {
			continue
		}

		newPath := filepath.Join(dir, newFilename)

		if config.Yes {
			renameFile(path, newPath)
		} else {
			confirmAndRename(path, newPath, &config)
		}
	}

	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, "Error reading stdin:", err)
		os.Exit(1)
	}
}

func parseArgs() Config {
	var config Config
	var numDigits int
	var truncateLength int
	var alpha bool

	flag.BoolVar(&config.ZeroTerminated, "0", false, "Use null character as separator")
	flag.BoolVar(&alpha, "alpha", false, "Replace non-alphanumeric characters with underscore")
	flag.IntVar(&numDigits, "num", 0, "add prefix number (0 to disable)")
	flag.IntVar(&truncateLength, "truncate", 0, "Truncate filename to length (0 to disable)")
	flag.BoolVar(&config.Yes, "y", false, "Do not prompt for confirmation")

	flag.Parse()

	if alpha {
		config.AlphaRegex = regexp.MustCompile(`[^a-zA-Z0-9]+`)
	}

	if numDigits > 0 {
		config.NumFormat = fmt.Sprintf("%%0%dd_%%s", numDigits)
	}
	if truncateLength > 0 {
		config.Truncate = true
		config.TruncateLength = truncateLength
	}

	args := flag.Args()
	for i := 0; i < len(args); i += 2 { // Loop through arguments in pairs
		if i+1 >= len(args) {
			fmt.Fprintln(os.Stderr, "Error: regex provided without replacement string")
			os.Exit(1)
		}
		re, err := regexp.Compile(args[i])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error compiling regex '%s': %v\n", args[i], err)
			os.Exit(1)
		}
		// Process replacement string to handle standard escape sequences
		// But ReplacAllString treats $ as special, so we keep as is.
		config.Replacements = append(config.Replacements, Replacement{
			Regex:       re,
			Replacement: args[i+1],
		})
	}

	return config
}

func scanNullTerminated(data []byte, atEOF bool) (advance int, token []byte, err error) {
	if atEOF && len(data) == 0 {
		return 0, nil, nil
	}
	if i := bytes.IndexByte(data, 0); i >= 0 {
		return i + 1, data[0:i], nil
	}
	if atEOF {
		return len(data), data, nil
	}
	return 0, nil, nil
}

func processFilename(filename string, index int, config Config) string {
	// 1. Regex Replacements
	for _, r := range config.Replacements {
		filename = r.Regex.ReplaceAllString(filename, r.Replacement)
	}

	ext := filepath.Ext(filename)
	name := filename[:len(filename)-len(ext)]

	// 2. Alpha Optimization
	if config.AlphaRegex != nil {
		name = config.AlphaRegex.ReplaceAllString(name, "_")
		name = strings.Trim(name, "_")
	}

	// 3. Truncation
	if config.Truncate && len(name) > config.TruncateLength {
		name = name[:config.TruncateLength]
	}

	// 4. Numbering
	if config.NumFormat != "" {
		name = fmt.Sprintf(config.NumFormat, index, name)
	}

	return name + ext
}

func renameFile(oldPath, newPath string) {
	err := os.Rename(oldPath, newPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error renaming '%s' to '%s': %v\n", oldPath, newPath, err)
	} else {
		fmt.Printf("Renamed: %s -> %s\n", oldPath, newPath)
	}
}

func confirmAndRename(oldPath, newPath string, config *Config) {
	fmt.Fprintf(os.Stderr, "Rename '%s' to '%s'? [y/n/a/q]: ", oldPath, newPath)

	// We need to read from /dev/tty for user confirmation if stdin is piped
	tty, err := os.Open("/dev/tty")
	if err != nil {
		// Fallback to stdin/stdout if TTY not available (unlikely in interactive usage)
		fmt.Fprintln(os.Stderr, "Error opening /dev/tty, assuming 'n'")
		return
	}
	defer tty.Close()

	reader := bufio.NewReader(tty)
	response, _ := reader.ReadString('\n')
	response = strings.TrimSpace(strings.ToLower(response))

	switch response {
	case "y":
		renameFile(oldPath, newPath)
	case "a":
		config.Yes = true
		renameFile(oldPath, newPath)
	case "q":
		os.Exit(0)
	case "n":
		// Do nothing
	default:
		// Default to no? or repeat? Let's treat as 'n' for safety
	}
}
