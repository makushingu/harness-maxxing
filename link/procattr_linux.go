package main

import "syscall"

// dieWithAgent: Linux kills the browser when the agent dies, even by SIGKILL (no stray browser
// left holding the profile).
func dieWithAgent(a *syscall.SysProcAttr) { a.Pdeathsig = syscall.SIGKILL }
