//go:build !linux && !windows && !darwin

package main

import "image"

// Other systems: the app connects but cannot see nor use the screen.
type noBackend struct{}

func newBackend(dir string, logf func(string, ...any)) backend { return noBackend{} }

func (noBackend) Info() backendInfo {
	return backendInfo{Note: "Screen and input are not supported on this system.", Code: "unsupported"}
}
func (noBackend) Capture() (image.Image, error)  { return nil, &opError{"unsupported", "no screen"} }
func (noBackend) Move(int, int) error            { return &opError{"unsupported", "no input"} }
func (noBackend) Button(string, bool, int) error { return &opError{"unsupported", "no input"} }
func (noBackend) Scroll(int, int) error          { return &opError{"unsupported", "no input"} }
func (noBackend) Key(string, bool) error         { return &opError{"unsupported", "no input"} }
func (noBackend) Text(string) error              { return &opError{"unsupported", "no input"} }
func (noBackend) Apps() ([]app, error)           { return nil, nil }
func (noBackend) Launch(app) error               { return &opError{"unsupported", "no apps"} }
func (noBackend) SetDisplay(int)                 {}
func (noBackend) Close()                         {}

// secureInput: no system-wide "password field focused" signal here; the live log shows typed text (cut).
func secureInput() bool { return false }
