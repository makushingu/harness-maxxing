package main

import "syscall"

// dieWithAgent: macOS has no parent-death signal; a normal exit of the agent still closes the browser.
func dieWithAgent(*syscall.SysProcAttr) {}
