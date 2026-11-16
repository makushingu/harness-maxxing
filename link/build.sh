#!/usr/bin/env bash
# Builds Harness Link for every target into dist/ (reproducible: CGO off, -trimpath, no VCS stamp, empty build id).
set -euo pipefail
cd "$(dirname "$0")"
VERSION="${VERSION:-0.1.0}"
GO="${GO:-go}"
export CGO_ENABLED=0 GOFLAGS="-trimpath -buildvcs=false"
LDFLAGS="-s -w -buildid= -X main.version=${VERSION}"
rm -rf dist && mkdir -p dist
# Windows: console app (it runs in the terminal window that started it); icon + version info (the product logo web/public/icons/icon-512.png, resized by go-winres) as rsrc_windows_*.syso, linked by go build
"$GO" run github.com/tc-hib/go-winres@v0.3.3 simply --arch amd64,arm64 --manifest gui --icon ../web/public/icons/icon-512.png \
  --product-name "Harness Link" --file-description "Harness Link - lets Harness Maxxing see and use this computer" \
  --product-version "$VERSION" --file-version "$VERSION" --original-filename harness-link.exe
build() { # goos goarch output [extra ldflags]
  GOOS=$1 GOARCH=$2 "$GO" build -ldflags "$LDFLAGS ${4:-}" -o "dist/$3" .
}
build windows amd64 harness-link-windows-amd64.exe
build windows arm64 harness-link-windows-arm64.exe
build darwin  arm64 harness-link-darwin-arm64
build darwin  amd64 harness-link-darwin-amd64
build linux   amd64 harness-link-linux-amd64
build linux   arm64 harness-link-linux-arm64
(cd dist && sha256sum harness-link-* > SHA256SUMS)
ls -l dist
