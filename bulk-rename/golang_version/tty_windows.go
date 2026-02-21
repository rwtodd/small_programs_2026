//go:build windows

package main

// SPDX-License-Identifier: MIT

import (
	"fmt"
	"os"
)

func openTTY() (*os.File, error) {
	return nil, fmt.Errorf("interactive mode not supported on Windows")
}

func registerInteractiveFlag(ptr *bool) {
	// No-op: flag not available on Windows
}
