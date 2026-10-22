#!/usr/bin/env bash
# Builds Harness PC for every target into dist/ (reproducible: -trimpath, no VCS stamp, empty build id).
set -euo pipefail
cd "$(dirname "$0")"
VERSION="${VERSION:-0.1.0}"
GO="${GO:-go}"
export CGO_ENABLED=0 GOFLAGS="-trimpath -buildvcs=false"
LDFLAGS="-s -w -buildid= -X main.version=${VERSION}"
rm -rf dist && mkdir -p dist
# Windows: icon + version info (the product logo web/public/icons/icon-512.png, resized by go-winres) as rsrc_windows_*.syso, linked by go build
"$GO" run github.com/tc-hib/go-winres@v0.3.3 simply --arch amd64,arm64 --manifest gui --icon ../web/public/icons/icon-512.png \
  --product-name "Harness PC" --file-description "Harness PC - browser of my PC for Harness Maxxing" \
  --product-version "$VERSION" --file-version "$VERSION" --original-filename HarnessPC.exe
build() { # goos goarch output [extra ldflags]
  GOOS=$1 GOARCH=$2 "$GO" build -ldflags "$LDFLAGS ${4:-}" -o "dist/$3" .
}
build windows amd64 HarnessPC-windows-amd64.exe "-H windowsgui"
build windows arm64 HarnessPC-windows-arm64.exe "-H windowsgui"
build darwin  arm64 harness-pc-darwin-arm64
build darwin  amd64 harness-pc-darwin-amd64
build linux   amd64 harness-pc-linux-amd64
build linux   arm64 harness-pc-linux-arm64
(cd dist && sha256sum HarnessPC-* harness-pc-* > SHA256SUMS)
ls -l dist
