package main

// SPDX-License-Identifier: MIT

import (
	"encoding/hex"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const (
	ansiBold  = "\033[1m"
	ansiReset = "\033[0m"
)

type stateTracker struct {
	isBold bool
}

func (s *stateTracker) setBold(target bool) string {
	if s.isBold == target {
		return ""
	}
	s.isBold = target
	if target {
		return ansiBold
	}
	return ansiReset
}

func main() {
	hexPattern := flag.String("l", "", "Literal hex pattern")
	regPattern := flag.String("r", "", "Regular expression pattern")
	ascPattern := flag.String("a", "", "ASCII literal pattern")
	contextSize := flag.Int("c", 0, "Minimum context in bytes")
	useBold := flag.Bool("b", false, "Use ANSI bolding")
	alignPara := flag.Bool("p", false, "Align output to 16-byte paragraphs (0x10)")

	flag.Parse()
	files := flag.Args()

	if len(files) == 0 || (*hexPattern == "" && *regPattern == "" && *ascPattern == "") {
		fmt.Println("Usage: bsearch [-l hex | -r regex | -a ascii] [-c context] [-b] [-p] <files>")
		return
	}

	var re *regexp.Regexp
	var err error
	switch {
	case *hexPattern != "":
		cleanHex := strings.ReplaceAll(*hexPattern, " ", "")
		raw, _ := hex.DecodeString(cleanHex)
		re, err = regexp.Compile(regexp.QuoteMeta(string(raw)))
	case *regPattern != "":
		re, err = regexp.Compile(strings.ReplaceAll(*regPattern, " ", ""))
	case *ascPattern != "":
		re, err = regexp.Compile(regexp.QuoteMeta(*ascPattern))
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "Pattern error: %v\n", err)
		return
	}

	multiFile := len(files) > 1
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			continue
		}

		matches := re.FindAllIndex(data, -1)
		for _, m := range matches {
			printMatch(data, m[0], m[1], *contextSize, filepath.Base(path), multiFile, *useBold, *alignPara)
		}
	}
}

func printMatch(data []byte, mStart, mEnd, minCtx int, fname string, showFname, wantBold, alignPara bool) {
	matchLen := mEnd - mStart
	var dStart, dEnd int

	if alignPara {
		// Alignment Mode: Start at the nearest 0x10 boundary providing enough context
		dStart = (mStart - minCtx) & ^0xF
		if dStart < 0 {
			dStart = 0
		}
		dEnd = (mEnd + minCtx + 15) & ^0xF
		if dEnd > len(data) {
			dEnd = len(data)
		}
	} else {
		// Centering Mode (Default)
		displaySize := ((matchLen + (minCtx * 2) + 15) / 16) * 16
		dStart = mStart - ((displaySize - matchLen) / 2)
		if dStart < 0 {
			dStart = 0
		}
		dEnd = dStart + displaySize
		if dEnd > len(data) {
			dEnd = len(data)
			dStart = dEnd - displaySize
			if dStart < 0 {
				dStart = 0
			}
		}
	}

	tracker := &stateTracker{}

	for i := dStart; i < dEnd; i += 16 {
		if showFname {
			fmt.Printf("%s ", fname)
		}

		// Handle the edge case: match starts exactly at the line address
		if i == mStart {
			fmt.Printf("%08x %s<", i, tracker.setBold(wantBold))
		} else {
			fmt.Print(tracker.setBold(false))
			fmt.Printf("%08x  ", i)
		}

		// --- Hex Side ---
		for j := i; j < i+16; j++ {
			if j < dEnd && j < len(data) {
				// Hex Digits
				shouldBoldDigit := wantBold && (j >= mStart && j < mEnd)
				fmt.Print(tracker.setBold(shouldBoldDigit))
				fmt.Printf("%02x", data[j])

				// Separator
				sep := " "
				if j+1 == mStart {
					sep = "<"
				} else if j == mEnd-1 {
					sep = ">"
				}

				shouldBoldSep := wantBold && (j+1 == mStart || (j >= mStart && j < mEnd))
				fmt.Print(tracker.setBold(shouldBoldSep))
				fmt.Print(sep)

				if (j - i) == 7 {
					fmt.Print(tracker.setBold(false))
					fmt.Print(" ")
				}
			} else {
				fmt.Print(tracker.setBold(false))
				fmt.Print("   ")
				if (j - i) == 7 {
					fmt.Print(" ")
				}
			}
		}

		fmt.Print(tracker.setBold(false) + " |")

		// --- ASCII Side ---
		for j := i; j < i+16 && j < dEnd && j < len(data); j++ {
			char := string(data[j])
			if data[j] < 32 || data[j] > 126 {
				char = "."
			}
			shouldBold := wantBold && (j >= mStart && j < mEnd)
			fmt.Print(tracker.setBold(shouldBold))
			fmt.Print(char)
		}
		fmt.Print(tracker.setBold(false) + "|")
		fmt.Println()
	}
}
