#!/usr/bin/env bash
# Builds the Harness Link APK: android/dist/harness-link.apk + harness-link.apk.sha256.
#
# Release signing key, from the environment (never committed):
#   HARNESS_LINK_KEYSTORE_B64       base64 of the keystore (.jks / .p12)
#   HARNESS_LINK_KEYSTORE_PASSWORD  keystore password
#   HARNESS_LINK_KEY_ALIAS          key alias
#   HARNESS_LINK_KEY_PASSWORD       key password
# Without them the release APK is signed with the local debug key (fine for tests, not for users:
# a phone only accepts updates signed with the same key).
#
# Needs a JDK 17+ and the Android SDK (ANDROID_HOME, default /opt/android-sdk).
#   ./build.sh            release APK (minified) + unit tests
#   ./build.sh --debug    debug APK (allows http to 10.0.2.2 / localhost, for the emulator)
set -euo pipefail
cd "$(dirname "$0")"

variant=release
[[ "${1:-}" == "--debug" ]] && variant=debug

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
if [[ ! -d "$ANDROID_HOME" ]]; then
  echo "Android SDK not found: set ANDROID_HOME" >&2
  exit 1
fi
[[ -f local.properties ]] || echo "sdk.dir=$ANDROID_HOME" > local.properties

if [[ -n "${HARNESS_LINK_KEYSTORE_B64:-}" ]]; then
  for v in HARNESS_LINK_KEYSTORE_PASSWORD HARNESS_LINK_KEY_ALIAS HARNESS_LINK_KEY_PASSWORD; do
    [[ -n "${!v:-}" ]] || { echo "$v is required with HARNESS_LINK_KEYSTORE_B64" >&2; exit 1; }
  done
  echo "Signing with the release key"
elif [[ "$variant" == release ]]; then
  echo "HARNESS_LINK_KEYSTORE_B64 not set: signing with the debug key" >&2
fi

task=assembleRelease
[[ "$variant" == debug ]] && task=assembleDebug
./gradlew --no-daemon -q testDebugUnitTest "$task"
# The decoded keystore never stays on disk.
rm -rf app/build/signing

mkdir -p dist
cp "app/build/outputs/apk/$variant/app-$variant.apk" dist/harness-link.apk
( cd dist && sha256sum harness-link.apk > harness-link.apk.sha256 )
cat dist/harness-link.apk.sha256
ls -l dist/harness-link.apk
