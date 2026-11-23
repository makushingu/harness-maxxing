package main

import (
	"slices"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Normalized key names, shared by every backend:
//
//	modifiers: ctrl, shift, alt, cmd (Command on macOS, Windows / Super key elsewhere)
//	named: enter, tab, esc, backspace, delete, insert, home, end, pageup, pagedown, left, up, right, down,
//	       space, capslock, printscreen, menu, f1 ... f24
//	any single character ("a", "1", "/", "é"): letters are lowercased.
var keyAliases = map[string]string{
	"control": "ctrl", "ctl": "ctrl",
	"option": "alt", "opt": "alt", "altgr": "alt",
	"command": "cmd", "super": "cmd", "win": "cmd", "windows": "cmd", "meta": "cmd", "logo": "cmd",
	"return": "enter", "ret": "enter",
	"escape": "esc",
	"del":    "delete", "forwarddelete": "delete",
	"ins":  "insert",
	"pgup": "pageup", "page_up": "pageup", "prior": "pageup",
	"pgdn": "pagedown", "page_down": "pagedown", "next": "pagedown",
	"arrowleft": "left", "arrowup": "up", "arrowright": "right", "arrowdown": "down",
	"spacebar": "space",
	"caps":     "capslock", "caps_lock": "capslock",
	"print": "printscreen", "prtsc": "printscreen", "prtscn": "printscreen",
	"apps": "menu", "contextmenu": "menu",
	"plus": "+", "minus": "-",
}

var namedKeys = map[string]bool{
	"ctrl": true, "shift": true, "alt": true, "cmd": true,
	"enter": true, "tab": true, "esc": true, "backspace": true, "delete": true, "insert": true,
	"home": true, "end": true, "pageup": true, "pagedown": true,
	"left": true, "up": true, "right": true, "down": true,
	"space": true, "capslock": true, "printscreen": true, "menu": true,
}

func isModifier(k string) bool { return k == "ctrl" || k == "shift" || k == "alt" || k == "cmd" }

// functionKey returns n for "f1" ... "f24", else 0.
func functionKey(k string) int {
	if len(k) < 2 || k[0] != 'f' {
		return 0
	}
	n, err := strconv.Atoi(k[1:])
	if err != nil || n < 1 || n > 24 {
		return 0
	}
	return n
}

// normKey returns the normalized name of one key, or "" if unknown.
func normKey(s string) string {
	if utf8.RuneCountInString(s) == 1 {
		r, _ := utf8.DecodeRuneInString(s)
		if unicode.IsControl(r) || unicode.IsSpace(r) {
			return ""
		}
		return string(unicode.ToLower(r))
	}
	k := strings.ToLower(s)
	if a, ok := keyAliases[k]; ok {
		k = a
	}
	if namedKeys[k] || functionKey(k) > 0 || utf8.RuneCountInString(k) == 1 {
		return k
	}
	return ""
}

// parseKeys reads "ctrl+s", "cmd+space", "enter", "alt+tab" or a space-separated sequence "ctrl+a delete".
// Each combo is its modifiers (in order, without duplicates) then at most one other key ("ctrl+shift" alone is fine).
func parseKeys(s string) ([][]string, error) {
	fields := strings.Fields(s)
	if len(fields) == 0 {
		return nil, badRequest("keys is required")
	}
	if len(fields) > maxCombos {
		return nil, badRequest("too many keys (at most %d combos)", maxCombos)
	}
	var out [][]string
	for _, f := range fields {
		var parts []string
		// "+" alone, or a trailing "+" ("ctrl++") means the plus key.
		switch {
		case f == "+":
			parts = []string{"+"}
		case strings.HasSuffix(f, "++"):
			parts = append(strings.Split(strings.TrimSuffix(f, "++"), "+"), "+")
		default:
			parts = strings.Split(f, "+")
		}
		var mods []string
		main := ""
		for _, p := range parts {
			k := normKey(p)
			if k == "" {
				return nil, badRequest("unknown key %q in %q", p, f)
			}
			if isModifier(k) {
				if main != "" {
					return nil, badRequest("modifier %q after the key in %q", p, f)
				}
				if !slices.Contains(mods, k) {
					mods = append(mods, k)
				}
				continue
			}
			if main != "" {
				return nil, badRequest("two keys in %q (use a space for a sequence)", f)
			}
			main = k
		}
		combo := mods
		if main != "" {
			combo = append(combo, main)
		}
		out = append(out, combo)
	}
	return out, nil
}

func compareFold(a, b string) int {
	return strings.Compare(strings.ToLower(a), strings.ToLower(b))
}
