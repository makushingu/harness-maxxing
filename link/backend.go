package main

import (
	"image"
	"slices"
)

const (
	capScreen = "screen"
	capInput  = "input"
	capApps   = "apps"
)

type screenInfo struct {
	W, H  int     // full resolution of the capture, in pixels
	Scale float64 // pixels per point of the system (1 = no scaling, 2 = Retina / 200 %)
}

// display is one screen of the computer, in the pixels of the system's global desktop.
type display struct {
	Name       string
	X, Y, W, H int
	Main       bool
}

// pickDisplay is the index to use among n screens for the wanted one (-1 or out of range: the main one).
func pickDisplay(l []display, want int) int {
	if want >= 0 && want < len(l) {
		return want
	}
	for i, d := range l {
		if d.Main {
			return i
		}
	}
	return 0
}

// backendInfo is what the hello frame reports; it is re-read before every request.
type backendInfo struct {
	Screen   *screenInfo
	Displays []display // every screen (one or more); Screen is Displays[Display]
	Display  int
	Input    bool
	Apps     bool
	Note     string // why something is missing, shown to the user in Harness
	Code     string // error code of the requests that cannot run (permission, unsupported, no_display)
}

func (i backendInfo) has(c string) bool {
	switch c {
	case capScreen:
		return i.Screen != nil
	case capInput:
		return i.Input && i.Screen != nil
	case capApps:
		return i.Apps
	}
	return false
}

func (i backendInfo) capsList() []string {
	l := []string{}
	for _, c := range []string{capScreen, capInput, capApps} {
		if i.has(c) {
			l = append(l, c)
		}
	}
	return l
}

// backend is the OS side: screen, input and apps. Coordinates are screen pixels (the capture's full size);
// key names are the normalized ones of keys.go. It never starts anything but a listed app.
type backend interface {
	Info() backendInfo
	Capture() (image.Image, error)
	Move(x, y int) error
	Button(button string, down bool, clicks int) error // clicks: 1, or 2 for the second click of a double click
	Scroll(dx, dy int) error                           // wheel notches, dy > 0 = down, dx > 0 = right
	Key(name string, down bool) error
	Text(s string) error
	Apps() ([]app, error)
	Launch(a app) error
	// SetDisplay chooses the screen Claude sees and uses (index in Info().Displays; -1 = the main one).
	SetDisplay(i int)
	Close()
}

func sortApps(l []app) []app {
	slices.SortFunc(l, func(a, b app) int {
		if c := compareFold(a.Name, b.Name); c != 0 {
			return c
		}
		return compareFold(a.ID, b.ID)
	})
	return slices.CompactFunc(l, func(a, b app) bool { return a.ID == b.ID })
}
