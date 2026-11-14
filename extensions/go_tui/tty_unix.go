//go:build !windows

package main

import "os"

// openTTY opens the controlling terminal for both input and output.
func openTTY() (in, out *os.File, err error) {
	tty, err := os.OpenFile("/dev/tty", os.O_RDWR, 0)
	if err != nil {
		return nil, nil, err
	}
	return tty, tty, nil
}
