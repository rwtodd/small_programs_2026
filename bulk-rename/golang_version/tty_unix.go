//go:build !windows

package main

// SPDX-License-Identifier: MIT

import (
	"flag"
	"os"
)

func openTTY() (*os.File, error) {
	return os.Open("/dev/tty")
}

func registerInteractiveFlag(ptr *bool) {
	flag.BoolVar(ptr, "i", false, "Prompt for confirmation before renaming")
}
