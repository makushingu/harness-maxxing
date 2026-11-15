package main

import (
	"bufio"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// Linux apps = the XDG .desktop files (freedesktop Desktop Entry spec). Kept free of build tags for the tests.

type xdgEntry struct {
	Name, Exec string
}

// parseDesktopFile reads the [Desktop Entry] group; ok is false for entries that are not launchable apps
// (not Type=Application, hidden, NoDisplay, terminal apps, no Exec).
func parseDesktopFile(r io.Reader) (xdgEntry, bool) {
	var e xdgEntry
	in := false
	typ, hidden, terminal := "", false, false
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64<<10), 64<<10)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || line[0] == '#' {
			continue
		}
		if line[0] == '[' {
			in = line == "[Desktop Entry]"
			continue
		}
		if !in {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		k, v = strings.TrimSpace(k), strings.TrimSpace(v)
		switch k {
		case "Type":
			typ = v
		case "Name":
			e.Name = unescapeDesktopValue(v)
		case "Exec":
			e.Exec = unescapeDesktopValue(v)
		case "NoDisplay", "Hidden":
			hidden = hidden || v == "true"
		case "Terminal":
			terminal = v == "true"
		}
	}
	return e, typ == "Application" && !hidden && !terminal && e.Name != "" && e.Exec != ""
}

// unescapeDesktopValue applies the string escapes of the spec (\s \n \t \r \\).
func unescapeDesktopValue(v string) string {
	if !strings.Contains(v, `\`) {
		return v
	}
	var b strings.Builder
	for i := 0; i < len(v); i++ {
		if v[i] == '\\' && i+1 < len(v) {
			i++
			switch v[i] {
			case 's':
				b.WriteByte(' ')
			case 'n':
				b.WriteByte('\n')
			case 't':
				b.WriteByte('\t')
			case 'r':
				b.WriteByte('\r')
			case '\\':
				b.WriteByte('\\')
			default:
				b.WriteByte('\\')
				b.WriteByte(v[i])
			}
			continue
		}
		b.WriteByte(v[i])
	}
	return b.String()
}

// parseExec splits an Exec value into argv (spec quoting rules) and drops the field codes (%f %U %i ...).
func parseExec(s string) ([]string, error) {
	var args []string
	var cur strings.Builder
	has, quoted := false, false
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case quoted && c == '\\' && i+1 < len(s) && strings.IndexByte("\"`$\\", s[i+1]) >= 0:
			i++
			cur.WriteByte(s[i])
		case c == '"':
			quoted = !quoted
			has = true
		case !quoted && (c == ' ' || c == '\t'):
			if has {
				args = append(args, cur.String())
				cur.Reset()
				has = false
			}
		default:
			cur.WriteByte(c)
			has = true
		}
	}
	if quoted {
		return nil, errors.New("unterminated quote in Exec")
	}
	if has {
		args = append(args, cur.String())
	}
	out := args[:0]
	for _, a := range args {
		if len(a) == 2 && a[0] == '%' && a != "%%" {
			continue // a lone field code: %f %F %u %U %i %c %k ...
		}
		var b strings.Builder
		for i := 0; i < len(a); i++ {
			if a[i] == '%' && i+1 < len(a) {
				i++
				if a[i] == '%' {
					b.WriteByte('%')
				}
				continue
			}
			b.WriteByte(a[i])
		}
		if b.Len() > 0 {
			out = append(out, b.String())
		}
	}
	if len(out) == 0 {
		return nil, errors.New("empty Exec")
	}
	return out, nil
}

// xdgAppDirs lists the applications folders, most important first (user, then system, then flatpak / snap).
func xdgAppDirs() []string {
	home, _ := os.UserHomeDir()
	dataHome := os.Getenv("XDG_DATA_HOME")
	if dataHome == "" && home != "" {
		dataHome = filepath.Join(home, ".local", "share")
	}
	dirs := os.Getenv("XDG_DATA_DIRS")
	if dirs == "" {
		dirs = "/usr/local/share:/usr/share"
	}
	var l []string
	if dataHome != "" {
		l = append(l, dataHome)
	}
	l = append(l, filepath.SplitList(dirs)...)
	if home != "" {
		l = append(l, filepath.Join(home, ".local", "share", "flatpak", "exports", "share"))
	}
	l = append(l, "/var/lib/flatpak/exports/share", "/var/lib/snapd/desktop")
	var out []string
	seen := map[string]bool{}
	for _, d := range l {
		d = filepath.Join(d, "applications")
		if d != "" && !seen[d] {
			seen[d] = true
			out = append(out, d)
		}
	}
	return out
}

// desktopApps lists the launchable .desktop files of dirs; the first file of an id wins (spec precedence).
func desktopApps(dirs []string) []app {
	seen := map[string]bool{}
	var l []app
	for _, d := range dirs {
		_ = filepath.WalkDir(d, func(p string, de os.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if de.IsDir() {
				if p != d && strings.Count(strings.TrimPrefix(p, d), string(filepath.Separator)) > 3 {
					return filepath.SkipDir
				}
				return nil
			}
			if !strings.HasSuffix(p, ".desktop") {
				return nil
			}
			rel, _ := filepath.Rel(d, p)
			id := strings.TrimSuffix(strings.ReplaceAll(rel, string(filepath.Separator), "-"), ".desktop")
			if seen[id] {
				return nil
			}
			seen[id] = true // a hidden user file also hides the system one
			f, err := os.Open(p)
			if err != nil {
				return nil
			}
			e, ok := parseDesktopFile(io.LimitReader(f, 256<<10))
			f.Close()
			if ok {
				l = append(l, app{ID: id, Name: e.Name, target: p})
			}
			return nil
		})
	}
	return sortApps(l)
}
