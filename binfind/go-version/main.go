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

	"github.com/rwtodd/Go.Forth/forth"
)

const (
	ansiColor = "\033[1;91m" // high-inensity red
	ansiReset = "\033[0m"
)

type stateTracker struct {
	hasColor bool
}

func (s *stateTracker) setColor(target bool) string {
	if s.hasColor == target {
		return ""
	}
	s.hasColor = target
	if target {
		return ansiColor
	}
	return ansiReset
}

func main() {
	hexPattern := flag.String("l", "", "Literal hex pattern")
	regPattern := flag.String("r", "", "Regular expression pattern")
	ascPattern := flag.String("a", "", "ASCII literal pattern")
	contextSize := flag.Int("c", 0, "Minimum context in bytes")
	noColor := flag.Bool("nocolor", false, "Use plain output with no ANSI codes")
	alignPara := flag.Bool("align", false, "Align output to 16-byte paragraphs (0x10)")
	forthExpr := flag.String("expr", "", "Forth code to run on each match")
	forthScript := flag.String("script", "", "File containing Forth code to run on each match")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: binfind [-l hex | -r regex | -a ascii] [-c context] [--nocolor] [--align] [--expr code] [--script file] <files>\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nForth expressions must leave an XT (execution token) on the stack.\n")
		fmt.Fprintf(os.Stderr, "The XT is called on each match with access to:\n")
		fmt.Fprintf(os.Stderr, "  data ( -- bytes)        Return matched file contents\n")
		fmt.Fprintf(os.Stderr, "  offset ( -- n)          Get current match offset\n")
		fmt.Fprintf(os.Stderr, "  offset! ( n -- )        Set match offset\n")
		fmt.Fprintf(os.Stderr, "  length ( -- n)          Get current match length\n")
		fmt.Fprintf(os.Stderr, "  length! ( n -- )        Set match length\n")
		fmt.Fprintf(os.Stderr, "  output-match ( -- )     Print the match using current settings\n")
	}

	flag.Parse()
	files := flag.Args()

	wantsANSI := !*noColor // if they don't want no color, give them color

	if len(files) == 0 || (*hexPattern == "" && *regPattern == "" && *ascPattern == "") {
		flag.Usage()
		os.Exit(1)
	}

	var re *regexp.Regexp
	var err error
	switch {
	case *hexPattern != "":
		cleanHex := strings.ReplaceAll(*hexPattern, " ", "")
		var raw []byte
		raw, err = hex.DecodeString(cleanHex)
		if err == nil {
			re, err = regexp.Compile(regexp.QuoteMeta(string(raw)))
		}
	case *regPattern != "":
		re, err = regexp.Compile(strings.ReplaceAll(*regPattern, " ", ""))
	case *ascPattern != "":
		re, err = regexp.Compile(regexp.QuoteMeta(*ascPattern))
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "Pattern error: %v\n", err)
		os.Exit(1)
	}

	multiFile := len(files) > 1
	var currentFname string
	var currentData []byte
	var currentOffset int
	var currentLength int

	vm := forth.NewVM(strings.NewReader(""), os.Stdout)
	vm.Define(forth.NewNativeWord("data", func(v *forth.VM) error {
		v.Push(currentData)
		return nil
	}))
	vm.Define(forth.NewNativeWord("offset", func(v *forth.VM) error {
		v.Push(int64(currentOffset))
		return nil
	}))
	vm.Define(forth.NewNativeWord("offset!", func(v *forth.VM) error {
		oRaw, err := v.Pop()
		if err != nil {
			return err
		}
		offset, ok := oRaw.(int64)
		if !ok {
			return fmt.Errorf("offset must be an integer")
		}
		currentOffset = int(offset)
		return nil
	}))
	vm.Define(forth.NewNativeWord("length", func(v *forth.VM) error {
		v.Push(int64(currentLength))
		return nil
	}))
	vm.Define(forth.NewNativeWord("length!", func(v *forth.VM) error {
		lRaw, err := v.Pop()
		if err != nil {
			return err
		}
		length, ok := lRaw.(int64)
		if !ok {
			return fmt.Errorf("length must be an integer")
		}
		currentLength = int(length)
		return nil
	}))
	vm.Define(forth.NewNativeWord("output-match", func(v *forth.VM) error {
		printMatch(currentData, currentOffset, currentOffset+currentLength, *contextSize, currentFname, multiFile, wantsANSI, *alignPara)
		return nil
	}))

	var forthCode string = "[ output-match ]"
	if *forthScript != "" {
		err := vm.Load(*forthScript)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Could not load script file: %v\n", err)
			os.Exit(1)
		}
	} else {

   	 	if *forthExpr != "" {
			forthCode = *forthExpr
		}
		err := vm.Eval(forthCode)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Could not evaluate FORTH: %v\n", err)
			os.Exit(1)
		}
	} 

	xtRaw, err := vm.Pop()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Expected an XT on the stack from Forth script\n")
		os.Exit(1)
	}
	userXT, ok := xtRaw.(forth.ExecutionToken)
	if !ok {
		fmt.Fprintf(os.Stderr, "Expected an Execution Token (XT), got %T\n", xtRaw)
		os.Exit(1)
	}
	vm.ResetState() // clear up anything the user might have sloppily left behind

	hadErrors := false
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			hadErrors = true
			continue
		}

		currentFname = filepath.Base(path)
		currentData = data
		matches := re.FindAllIndex(data, -1)
		for _, m := range matches {
			currentOffset = m[0]
			currentLength = m[1] - m[0]
			err := userXT.Run(vm)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error matching in %s at %x: %v\n", currentFname, m[0], err)
				hadErrors = true
			}
			vm.ResetState()
		}
	}
	if hadErrors { // report to the OS that we errored out
		os.Exit(1)
	}
}

func printMatch(data []byte, mStart, mEnd, minCtx int, fname string, showFname, wantsANSI, alignPara bool) {
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
			fmt.Printf("%08x %s<", i, tracker.setColor(wantsANSI))
		} else {
			fmt.Printf("%08x  ", i)
		}

		// --- Hex Side ---
		for j := i; j < i+16; j++ {
			if j < dEnd && j < len(data) {
				// Hex Digits
				shouldColorDigit := wantsANSI && (j >= mStart && j < mEnd)
				fmt.Print(tracker.setColor(shouldColorDigit))
				fmt.Printf("%02x", data[j])

				// Separator
				colorStr := tracker.setColor(wantsANSI && (j+1 == mStart || (j >= mStart && j < mEnd)))
				var extraSep string
				if (j - i) == 7 {
					extraSep = " "
				} else {
					extraSep = ""
				}
				if j+1 == mStart && j+1 != i+16 {
					fmt.Printf("%s%s<", extraSep, colorStr)
				} else if j == mEnd-1 {
					fmt.Printf("%s>%s", colorStr, extraSep)
				} else {
					fmt.Print(" ")
					fmt.Print(extraSep)
				}
			} else {
				fmt.Print(tracker.setColor(false))
				fmt.Print("   ")
				if (j - i) == 7 {
					fmt.Print(" ")
				}
			}
		}

		fmt.Print(tracker.setColor(false) + " |")

		// --- ASCII Side ---
		for j := i; j < i+16 && j < dEnd && j < len(data); j++ {
			char := string(data[j])
			if data[j] < 32 || data[j] > 126 {
				char = "."
			}
			shouldBold := wantsANSI && (j >= mStart && j < mEnd)
			fmt.Print(tracker.setColor(shouldBold))
			fmt.Print(char)
		}
		fmt.Print(tracker.setColor(false) + "|")
		fmt.Println()
	}
}
