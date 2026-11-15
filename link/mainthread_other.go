//go:build !darwin

package main

func runMain(f func() int) int { return f() }

func runOnMain(fn func()) { fn() }
