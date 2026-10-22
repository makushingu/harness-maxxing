package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

const (
	trailerMagic  = "HMPCCFG1"
	maxTrailerLen = 64 << 10
	configName    = "config.json"
	logName       = "harness-pc.log"
	lockName      = "harness-pc.lock"
)

// Trailer is the pairing data the server appends to the generic binary.
type Trailer struct {
	Server    string `json:"server"`
	Code      string `json:"code"`
	Browser   string `json:"browser"`
	Autostart bool   `json:"autostart"`
}

// Config is what the agent keeps after pairing (config.json, 0600).
type Config struct {
	Server     string `json:"server"`
	DeviceID   string `json:"device_id"`
	Token      string `json:"token"`
	Browser    string `json:"browser"`
	Autostart  bool   `json:"autostart"`
	PairedCode string `json:"paired_code,omitempty"`
}

// configDir returns the per-user directory of the agent (HARNESS_PC_CONFIG_DIR overrides it).
func configDir() (string, error) {
	if d := os.Getenv("HARNESS_PC_CONFIG_DIR"); d != "" {
		return filepath.Abs(d)
	}
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	if runtime.GOOS == "linux" || (runtime.GOOS != "windows" && runtime.GOOS != "darwin") {
		return filepath.Join(base, "harness-pc"), nil
	}
	return filepath.Join(base, "HarnessPC"), nil
}

func ensureDir(dir string) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	if runtime.GOOS != "windows" {
		return os.Chmod(dir, 0o700)
	}
	return nil
}

// validateServer accepts https URLs, and plain http only for 127.0.0.1 / localhost.
// It returns the URL without a trailing slash.
func validateServer(s string) (string, error) {
	u, err := url.Parse(strings.TrimSpace(s))
	if err != nil {
		return "", fmt.Errorf("bad server URL: %w", err)
	}
	if u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Opaque != "" {
		return "", errors.New("bad server URL")
	}
	switch u.Scheme {
	case "https":
	case "http":
		h := u.Hostname()
		if h != "127.0.0.1" && h != "localhost" {
			return "", errors.New("server URL must use https")
		}
	default:
		return "", errors.New("server URL must use https")
	}
	return strings.TrimRight(u.Scheme+"://"+u.Host+u.EscapedPath(), "/"), nil
}

// parseTrailer reads the pairing trailer at the end of data (the tail of the executable).
// It returns (nil, nil) when there is no trailer.
func parseTrailer(data []byte) (*Trailer, error) {
	if len(data) < len(trailerMagic)+4 || !bytes.HasSuffix(data, []byte(trailerMagic)) {
		return nil, nil
	}
	end := len(data) - len(trailerMagic)
	n := binary.BigEndian.Uint32(data[end-4 : end])
	if n == 0 || n > maxTrailerLen || int(n) > end-4 {
		return nil, errors.New("corrupt trailer length")
	}
	raw := data[end-4-int(n) : end-4]
	var t Trailer
	if err := json.Unmarshal(raw, &t); err != nil {
		return nil, fmt.Errorf("corrupt trailer: %w", err)
	}
	srv, err := validateServer(t.Server)
	if err != nil {
		return nil, err
	}
	t.Server = srv
	if t.Code == "" || len(t.Code) > 128 {
		return nil, errors.New("trailer has no pairing code")
	}
	if t.Browser != "" && !knownBrowser(t.Browser) {
		return nil, fmt.Errorf("unknown browser %q", t.Browser)
	}
	return &t, nil
}

// readTrailer reads the trailer of the given executable.
func readTrailer(path string) (*Trailer, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	size := st.Size()
	tail := int64(len(trailerMagic) + 4)
	if size < tail {
		return nil, nil
	}
	foot := make([]byte, tail)
	if _, err := f.ReadAt(foot, size-tail); err != nil {
		return nil, err
	}
	if !bytes.HasSuffix(foot, []byte(trailerMagic)) {
		return nil, nil
	}
	n := int64(binary.BigEndian.Uint32(foot[:4]))
	if n == 0 || n > maxTrailerLen || n > size-tail {
		return nil, errors.New("corrupt trailer length")
	}
	buf := make([]byte, n+tail)
	if _, err := f.ReadAt(buf, size-tail-n); err != nil && !errors.Is(err, io.EOF) {
		return nil, err
	}
	return parseTrailer(buf)
}

func loadConfig(dir string) (*Config, error) {
	p := filepath.Join(dir, configName)
	b, err := os.ReadFile(p)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if runtime.GOOS != "windows" {
		if st, err := os.Stat(p); err == nil && st.Mode().Perm()&0o077 != 0 {
			_ = os.Chmod(p, 0o600)
		}
	}
	var c Config
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, fmt.Errorf("corrupt %s: %w", configName, err)
	}
	srv, err := validateServer(c.Server)
	if err != nil {
		return nil, err
	}
	c.Server = srv
	if c.Token == "" {
		return nil, errors.New("config has no token")
	}
	if c.Browser != "" && !knownBrowser(c.Browser) {
		c.Browser = ""
	}
	return &c, nil
}

// saveConfig writes config.json atomically with mode 0600.
func saveConfig(dir string, c *Config) error {
	if err := ensureDir(dir); err != nil {
		return err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(filepath.Join(dir, configName), b, 0o600)
}

func deleteConfig(dir string) error {
	err := os.Remove(filepath.Join(dir, configName))
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

func writeFileAtomic(path string, data []byte, mode os.FileMode) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".tmp-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	ok := false
	defer func() {
		if !ok {
			tmp.Close()
			os.Remove(name)
		}
	}()
	if err := tmp.Chmod(mode); err != nil && runtime.GOOS != "windows" {
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		return err
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, path); err != nil {
		return err
	}
	ok = true
	return nil
}
