#!/usr/bin/env bash
# Build the Android app.
#   npm run apk               → test build: android/app/build/outputs/apk/debug/app-debug.apk
#   npm run release:android   → Play Store build: android/app/build/outputs/bundle/release/app-release.aab
#                               (+ a signed APK you can share directly)
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-debug}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
# Capacitor 8 needs a full JDK 21 (with javac). Android Studio ships one.
if [ -z "${JAVA_HOME:-}" ] && [ -x /opt/android-studio/jbr/bin/javac ]; then export JAVA_HOME=/opt/android-studio/jbr; fi

if [ "$MODE" = "release" ]; then
  if grep -q '"devUrl": "[^"]' app.settings.json; then
    echo "✗ app.settings.json has a devUrl. Clear it before a store build."; exit 1
  fi
  if [ ! -f android/keystore.properties ]; then
    echo "✗ No signing key. Create one first: bash scripts/make-keystore.sh (see PUBLISHING.md)"; exit 1
  fi
  export ATTENDPRO_RELEASE=1
fi

npm run sync -- android
cd android
if [ "$MODE" = "release" ]; then
  ./gradlew --quiet bundleRelease assembleRelease
  echo "✓ Play Store bundle: mobile/android/app/build/outputs/bundle/release/app-release.aab"
  echo "✓ Signed APK:        mobile/android/app/build/outputs/apk/release/app-release.apk"
else
  ./gradlew --quiet assembleDebug
  echo "✓ Test APK: mobile/android/app/build/outputs/apk/debug/app-debug.apk"
fi
