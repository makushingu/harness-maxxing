package main

import (
	"fmt"
	"image"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestToScreen(t *testing.T) {
	for _, tc := range []struct {
		v, cap float64
		real   int
		want   int
	}{
		{640, 1280, 1920, 960}, {0, 1280, 1920, 0}, {1279, 1280, 1920, 1919}, {1280, 1280, 1920, 1919},
		{-3, 1280, 1920, 0}, {500, 0, 1920, 500}, {5000, 0, 1920, 1919}, {360, 720, 2160, 1080},
		{100.4, 1280, 2560, 201},
	} {
		if got := toScreen(tc.v, tc.cap, tc.real); got != tc.want {
			t.Errorf("toScreen(%v, %v, %d) = %d, want %d", tc.v, tc.cap, tc.real, got, tc.want)
		}
	}
}

func TestDownscale(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 2880, 1800))
	for _, tc := range []struct{ maxW, w, h int }{{1280, 1280, 800}, {0, 2880, 1800}, {4000, 2880, 1800}, {1000, 1000, 625}, {3, 16, 10}} {
		b := downscale(img, tc.maxW).Bounds()
		if b.Dx() != tc.w || b.Dy() != tc.h {
			t.Errorf("downscale(%d) = %dx%d, want %dx%d", tc.maxW, b.Dx(), b.Dy(), tc.w, tc.h)
		}
	}
}

func TestParseKeys(t *testing.T) {
	good := map[string]string{
		"ctrl+s":             "[[ctrl s]]",
		"cmd+space":          "[[cmd space]]",
		"enter":              "[[enter]]",
		"Return":             "[[enter]]",
		"alt+tab":            "[[alt tab]]",
		"Ctrl+Shift+T":       "[[ctrl shift t]]",
		"super":              "[[cmd]]",
		"ctrl+a delete":      "[[ctrl a] [delete]]",
		"ctrl++":             "[[ctrl +]]",
		"ctrl+plus":          "[[ctrl +]]",
		"+":                  "[[+]]",
		"F5":                 "[[f5]]",
		"cmd+option+esc":     "[[cmd alt esc]]",
		"ctrl+ctrl+c":        "[[ctrl c]]",
		"ctrl+/":             "[[ctrl /]]",
		"é":                  "[[é]]",
		"ArrowDown PageDown": "[[down] [pagedown]]",
	}
	for in, want := range good {
		got, err := parseKeys(in)
		if err != nil || fmt.Sprint(got) != want {
			t.Errorf("parseKeys(%q) = %v %v, want %s", in, got, err, want)
		}
	}
	for _, in := range []string{"", "ctrl+nope", "a+b", "s+ctrl", "f25", "ctrl+", strings.Repeat("a ", 40)} {
		if got, err := parseKeys(in); err == nil {
			t.Errorf("parseKeys(%q) accepted: %v", in, got)
		}
	}
}

func TestDragPathAndNotches(t *testing.T) {
	p := dragPath(0, 0, 100, 50, 64)
	if len(p) != 4 || p[3] != [2]int{100, 50} || p[0] != [2]int{25, 13} {
		t.Fatalf("drag path %v", p)
	}
	if len(dragPath(0, 0, 1, 1, 0)) != 2 {
		t.Fatal("minimum two steps")
	}
	for v, want := range map[float64]int{0: 0, 0.2: 1, -0.4: -1, 2.6: 3, -500: -maxScroll, 1e9: maxScroll} {
		if got := notches(v); got != want {
			t.Errorf("notches(%v) = %d, want %d", v, got, want)
		}
	}
}

func TestParseExec(t *testing.T) {
	good := map[string]string{
		`firefox %u`:                                  `[firefox]`,
		`/usr/bin/gimp-2.10 %U`:                       `[/usr/bin/gimp-2.10]`,
		`"/opt/My App/app" --new-window %F`:           `[/opt/My App/app --new-window]`,
		`sh -c "echo \"hi\" \$HOME"`:                  `[sh -c echo "hi" $HOME]`,
		`app --name=%c --icon %i --pct=100%%`:         `[app --name= --icon --pct=100%]`,
		`flatpak run --branch=stable org.example.App`: `[flatpak run --branch=stable org.example.App]`,
	}
	for in, want := range good {
		got, err := parseExec(in)
		if err != nil || fmt.Sprint(got) != want {
			t.Errorf("parseExec(%q) = %q %v, want %s", in, got, err, want)
		}
	}
	for _, in := range []string{`"unterminated`, `%f %u`, ``} {
		if got, err := parseExec(in); err == nil {
			t.Errorf("parseExec(%q) accepted %q", in, got)
		}
	}
}

func TestDesktopApps(t *testing.T) {
	user, sys := t.TempDir(), t.TempDir()
	write := func(dir, name, body string) {
		p := filepath.Join(dir, name)
		os.MkdirAll(filepath.Dir(p), 0o755)
		os.WriteFile(p, []byte(body), 0o644)
	}
	write(sys, "org.example.Editor.desktop", "[Desktop Entry]\nType=Application\nName=Editor\nName[fr]=Éditeur\nExec=editor %F\n[Desktop Action new]\nName=New window\nExec=editor --new\n")
	write(sys, "hidden.desktop", "[Desktop Entry]\nType=Application\nName=Hidden\nExec=x\nNoDisplay=true\n")
	write(sys, "term.desktop", "[Desktop Entry]\nType=Application\nName=Top\nExec=top\nTerminal=true\n")
	write(sys, "link.desktop", "[Desktop Entry]\nType=Link\nName=Site\nURL=https://ui.example.com\n")
	write(sys, "kde/calc.desktop", "[Desktop Entry]\nType=Application\nName=Calculator\nExec=calc\n")
	write(sys, "gone.desktop", "[Desktop Entry]\nType=Application\nName=Gone\nExec=gone\n")
	write(user, "gone.desktop", "[Desktop Entry]\nType=Application\nName=Gone\nExec=gone\nHidden=true\n") // user hides it
	l := desktopApps([]string{user, sys})
	var got []string
	for _, a := range l {
		got = append(got, a.ID+"="+a.Name)
	}
	if strings.Join(got, ",") != "kde-calc=Calculator,org.example.Editor=Editor" {
		t.Fatalf("apps %v", got)
	}
}
