#!/usr/bin/env bash
# Refresh the pinned third-party versions and checksums of server/maxxing/deps.toml (maintainers only - the
# installer never runs this). Every value is checked before it is written:
#   uv          latest release, its sha256.sum must match the archives downloaded here
#   node        latest NODE_MAJOR release, SHASUMS256.txt.asc must carry a good signature from a key of
#               github.com/nodejs/release-keys
#   claude      Claude Code's `stable` version, sha256 of its release manifest (the installer checks the binary
#               against it; installs update themselves afterwards)
#   caddy       the repository key must still have the pinned fingerprint (a change is reported, not written)
#   scrapling   latest version on PyPI; templates/scrapling/requirements.txt re-resolved with every hash
#   remotion    reported only (templates/remotion/package-lock.json is bumped with npm by hand, then tested)
#   garage      reported only (its pins live in server/maxxing/infra/actions.py)
# Usage: scripts/bump-pins.sh [NODE_MAJOR (22)]   then review `git diff`, run the tests and an install in a container.
set -euo pipefail
cd "$(dirname "$0")/.."
F=server/maxxing/deps.toml
MAJOR=${1:-22}
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
export GNUPGHOME="$W/gnupg"; mkdir -m 700 "$GNUPGHOME"

# pin SECTION KEY VALUE [SUBKEY] - rewrite one value of deps.toml in place (format kept, comments kept)
pin() {
  python3 -I - "$F" "$@" <<'PY'
import re, sys
path, sec, key, val = sys.argv[1:5]
sub = sys.argv[5] if len(sys.argv) > 5 else None
lines = open(path, encoding="utf-8").read().split("\n")
cur = None
for i, ln in enumerate(lines):
    m = re.fullmatch(r"\[([A-Za-z0-9_-]+)\]", ln.strip())
    if m:
        cur = m.group(1)
        continue
    if cur != sec or not re.match(rf"{key}\s*=", ln):
        continue
    if sub is None:
        lines[i] = f'{key} = "{val}"'
    else:
        lines[i], n = re.subn(rf'(\b{sub}\s*=\s*")[^"]*(")', rf"\g<1>{val}\g<2>", ln)
        if not n:
            sys.exit(f"{sec}.{key}.{sub} not found")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"  {sec}.{key}{'.' + sub if sub else ''} = {val}")
    sys.exit(0)
sys.exit(f"{sec}.{key} not found in {path}")
PY
}
cur() { sed -n "/^\[$1\]/,/^\[/p" "$F" | sed -n "s/^$2 = \"\(.*\)\"$/\1/p" | head -n1; }

# uv
uv=$(curl -fsSL https://api.github.com/repos/astral-sh/uv/releases/latest | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)
[ -n "$uv" ] || { echo "uv: no release found" >&2; exit 1; }
curl -fsSL "https://github.com/astral-sh/uv/releases/download/$uv/sha256.sum" -o "$W/uv.sum"
pin uv version "$uv"
for a in x86_64 aarch64; do
  f="uv-$a-unknown-linux-gnu.tar.gz"
  curl -fsSL "https://github.com/astral-sh/uv/releases/download/$uv/$f" -o "$W/$f"
  s=$(awk -v f="$f" '{n=$2; sub(/^\*/, "", n)} n==f {print $1}' "$W/uv.sum")
  [ "$(sha256sum "$W/$f" | cut -d' ' -f1)" = "$s" ] || { echo "uv $a: checksum mismatch" >&2; exit 1; }
  pin uv sha256 "$s" "$a"
done

# Node.js
curl -fsSL "https://nodejs.org/dist/latest-v$MAJOR.x/SHASUMS256.txt.asc" -o "$W/node.asc"
curl -fsSL https://raw.githubusercontent.com/nodejs/release-keys/main/keys.list -o "$W/keys.list"
while read -r k; do
  [ -n "$k" ] && curl -fsSL "https://raw.githubusercontent.com/nodejs/release-keys/main/keys/$k.asc" | gpg -q --import 2>/dev/null
done < "$W/keys.list"
gpg --status-file "$W/node.status" --decrypt "$W/node.asc" >"$W/node.sums" 2>/dev/null || true
grep -q '^\[GNUPG:\] GOODSIG' "$W/node.status" \
  || { echo "Node.js: SHASUMS256.txt.asc has no good signature from a Node.js releaser" >&2; exit 1; }
node=$(awk '$2 ~ /linux-x64\.tar\.xz$/ {sub(/^node-v/, "", $2); sub(/-linux-x64\.tar\.xz$/, "", $2); print $2}' "$W/node.sums")
pin node version "$node"
for a in x86_64:x64 aarch64:arm64; do
  pin node sha256 "$(awk -v f="node-v$node-linux-${a#*:}.tar.xz" '$2==f {print $1}' "$W/node.sums")" "${a%%:*}"
done

# Claude Code (stable channel)
cl=$(curl -fsSL https://downloads.claude.ai/claude-code-releases/stable)
printf '%s' "$cl" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "Claude Code: no stable version" >&2; exit 1; }
curl -fsSL "https://downloads.claude.ai/claude-code-releases/$cl/manifest.json" -o "$W/claude.json"
pin claude version "$cl"
for a in x86_64:x64 aarch64:arm64; do
  s=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["platforms"]["linux-" + sys.argv[2]]["checksum"])' "$W/claude.json" "${a#*:}")
  printf '%s' "$s" | grep -Eq '^[0-9a-f]{64}$' || { echo "Claude Code ${a#*:}: no checksum" >&2; exit 1; }
  pin claude sha256 "$s" "${a%%:*}"
done

# Caddy key
fpr=$(curl -fsSL "$(cur caddy key_url)" | gpg --show-keys --with-colons 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}')
want=$(cur caddy key_fingerprint)
if [ "$fpr" = "$want" ]; then echo "  caddy.key_fingerprint unchanged"
else echo "  WARNING: the Caddy key is now $fpr (pinned: $want) - check https://caddyserver.com/docs/install before changing it" >&2; fi

# Scrapling + its hash-locked requirements
scr=$(curl -fsSL https://pypi.org/pypi/scrapling/json | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])')
if [ -n "$scr" ]; then
  pin scrapling version "$scr"
  echo "scrapling[fetchers,rag]==$scr" > "$W/in.txt"
  UV_CACHE_DIR="$W/uvcache" uv pip compile "$W/in.txt" --universal --generate-hashes --python-version 3.12 \
    --no-header --no-annotate -q -o "$W/req.txt"
  { printf '# Scrapling and every package it needs, each pinned with its sha256 (installed with uv pip install --require-hashes).\n'
    printf '# Generated by scripts/bump-pins.sh from: scrapling[fetchers,rag]==%s (Python 3.12, every platform).\n' "$scr"
    cat "$W/req.txt"; } > templates/scrapling/requirements.txt
  echo "  templates/scrapling/requirements.txt re-resolved ($(grep -cE '^[a-z]' templates/scrapling/requirements.txt) packages)"
fi

echo "  remotion: $(cur remotion version) (bump templates/remotion/package.json + lock with npm, then the remotion pin)"
echo "  garage: pinned in server/maxxing/infra/actions.py"
echo "done - review: git diff $F templates/scrapling"
