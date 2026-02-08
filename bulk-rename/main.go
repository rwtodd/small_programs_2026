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
	Interactive    bool
	Apply          bool
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

	var hasErrors bool
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
			fmt.Printf("Skipping: %s (no change)\n", path)
			continue
		}

		if config.Apply {
			if err := renameFile(dir, filename, newFilename); err != nil {
				hasErrors = true
			}
		} else if config.Interactive {
			if err := confirmAndRename(dir, filename, newFilename, &config); err != nil {
				hasErrors = true
			}
		} else {
			// Dry Run (Default)
			fmt.Printf("Renamed (Dry Run): %s -> %s\n", filepath.Join(dir, filename), newFilename)
		}
	}

	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, "Error reading stdin:", err)
		os.Exit(1)
	}

	if hasErrors {
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
	registerInteractiveFlag(&config.Interactive)
	flag.BoolVar(&config.Apply, "y", false, "Apply renames without confirmation")

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

func renameFile(dir, oldName, newName string) error {
	oldPath := filepath.Join(dir, oldName)
	newPath := filepath.Join(dir, newName)
	err := os.Rename(oldPath, newPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error renaming '%s' to '%s': %v\n", oldPath, newPath, err)
		return err
	}
	// print dir/old -> new (elided dir)
	fmt.Printf("Renamed: %s -> %s\n", oldPath, newName)
	return nil
}

func confirmAndRename(dir, oldName, newName string, config *Config) error {
	oldPath := filepath.Join(dir, oldName)
	// For prompt, use full paths or just names? User asked for succinct output.
	// Let's use oldPath -> newName as requested for succinctness, but prompt might need to be clear.
	// "Rename 'dir/old' to 'new'?"

	fmt.Fprintf(os.Stderr, "Rename '%s' to '%s'? [y/n/a/q]: ", oldPath, newName)

	// openTTY is platform dependent
	tty, err := openTTY()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error opening TTY: %v\n", err)
		return err
	}
	defer tty.Close()

	reader := bufio.NewReader(tty)
	response, _ := reader.ReadString('\n')
	response = strings.TrimSpace(strings.ToLower(response))

	switch response {
	case "a":
		config.Apply = true
		fallthrough
	case "y":
		return renameFile(dir, oldName, newName)
	case "q":
		os.Exit(0)
	case "n":
		// Do nothing
		return nil
	default:
		// Default to no? or repeat? Let's treat as 'n' for safety
		return nil
	}
	return nil
}
