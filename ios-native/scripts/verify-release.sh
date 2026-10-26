#!/bin/bash
# Verify the exported .ipa before it goes to TestFlight.
#   ./scripts/verify-release.sh build/export/Zopedia.ipa 1.0.39
set -euo pipefail

IPA="${1:?usage: verify-release.sh <ipa> <expected-marketing-version>}"
EXPECTED_VERSION="${2:?missing expected marketing version}"

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/Applications/Xcode.app/Contents/Developer/usr/bin"
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

unzip -q "$IPA" -d "$WORK"
APP="$(find "$WORK/Payload" -maxdepth 1 -name '*.app' -type d | head -1)"
[ -n "$APP" ] || { echo "no .app inside $IPA" >&2; exit 1; }

PLIST="$APP/Info.plist"
get() {
  /usr/libexec/PlistBuddy -c "Print :$1" "$PLIST" 2>/dev/null || true
}

fail() { echo "FAIL: $*" >&2; exit 1; }

[ "$(get CFBundleIdentifier)" = "com.zopedia.client" ] \
  || fail "bundle id is $(get CFBundleIdentifier)"
[ "$(get CFBundleDisplayName)" = "Zopedia" ] \
  || fail "display name is $(get CFBundleDisplayName)"
[ "$(get CFBundleShortVersionString)" = "$EXPECTED_VERSION" ] \
  || fail "version is $(get CFBundleShortVersionString), expected $EXPECTED_VERSION"
[ "$(get MinimumOSVersion)" = "17.0" ] \
  || fail "minimum OS is $(get MinimumOSVersion), expected 17.0"
[ "$(get ITSAppUsesNonExemptEncryption)" = "false" ] \
  || fail "ITSAppUsesNonExemptEncryption is not false"
[ -n "$(get CFBundleIcons)" ] || fail "no CFBundleIcons (app icon missing)"
[ -f "$APP/PrivacyInfo.xcprivacy" ] || fail "privacy manifest is missing"

if /usr/libexec/PlistBuddy -c "Print :NSAppTransportSecurity:NSAllowsArbitraryLoads" "$PLIST" 2>/dev/null | grep -qi true; then
  fail "NSAllowsArbitraryLoads is present"
fi

if ! codesign -dv "$APP" 2>&1 | grep -q "TeamIdentifier=6NHRH72J3M"; then
  fail "bundle is not signed by team 6NHRH72J3M"
fi

echo "release verification passed: $EXPECTED_VERSION, com.zopedia.client, iOS 17.0"
