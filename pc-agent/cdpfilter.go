package main

import (
	"encoding/json"
	"net/url"
	"strings"
)

// The agent, not the server, is the boundary: whatever the server sends (even a compromised one), the
// browser can only be driven like a person would - no file of the PC is read, written or uploaded.

// blockedMethods are DevTools commands that reach past the browser: downloads to any folder, files given
// to pages, OS-level permissions and installs, raw protocol access, local network resources.
var blockedMethods = map[string]bool{
	"Browser.setDownloadBehavior":   true,
	"Page.setDownloadBehavior":      true,
	"Browser.grantPermissions":      true,
	"Browser.setPermission":         true,
	"Browser.executeBrowserCommand": true,
	"DOM.setFileInputFiles":         true,
	"Network.loadNetworkResource":   true,
	"Target.exposeDevToolsProtocol": true,
	"Target.setRemoteLocations":     true,
}

// blockedDomains: whole protocol domains with no use for driving pages.
var blockedDomains = map[string]bool{
	"Extensions": true, "PWA": true, "Tethering": true, "FileSystem": true, "BluetoothEmulation": true,
}

const maxCommand = 1 << 20 // a command from the server (the browser's answers may be bigger: screenshots)

type cdpCall struct {
	ID        json.RawMessage `json:"id"`
	SessionID string          `json:"sessionId,omitempty"`
	Method    string          `json:"method"`
	Params    struct {
		URL  *string `json:"url"`
		Data *struct {
			Files []string `json:"files"`
		} `json:"data"`
	} `json:"params"`
}

// allowedURL: pages only (http, https, about:blank, data) - never file:, chrome:, view-source:...
func allowedURL(raw string) bool {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return false
	}
	switch strings.ToLower(u.Scheme) {
	case "http", "https", "data":
		return true
	case "about":
		return strings.EqualFold(u.Opaque, "blank") || strings.EqualFold(u.Opaque, "srcdoc")
	}
	return false
}

// checkCommand returns "" when the command may go to the browser, else why it is refused.
func checkCommand(d string) (reason string, c cdpCall) {
	if len(d) > maxCommand {
		return "command too large", c
	}
	if err := json.Unmarshal([]byte(d), &c); err != nil || c.Method == "" {
		return "not a DevTools command", c
	}
	domain, _, _ := strings.Cut(c.Method, ".")
	if blockedMethods[c.Method] || blockedDomains[domain] {
		return c.Method + " is not allowed by Harness PC", c
	}
	if c.Params.URL != nil && !allowedURL(*c.Params.URL) {
		return "only http(s) pages can be opened by Harness PC", c
	}
	if c.Params.Data != nil && len(c.Params.Data.Files) > 0 {
		return "files of the PC cannot be dragged into pages", c
	}
	return "", c
}

// refusal is the DevTools error answer for a refused command (nil when it had no id to answer).
func refusal(c cdpCall, reason string) []byte {
	if len(c.ID) == 0 {
		return nil
	}
	m := map[string]any{"id": c.ID, "error": map[string]any{"code": -32000, "message": reason}}
	if c.SessionID != "" {
		m["sessionId"] = c.SessionID
	}
	b, _ := json.Marshal(m)
	return b
}
