#!/usr/bin/env bash
# Creates the Android upload key that signs every Play Store release of AttendPro.
# BACK UP the two files it creates (outside git). Without them you can't publish updates
# until Google resets your upload key.
set -euo pipefail
cd "$(dirname "$0")/../android"
STORE="${ATTENDPRO_KEYSTORE:-$HOME/attendpro-upload.jks}"
if [ -f keystore.properties ] || [ -f "$STORE" ]; then
  echo "A key already exists ($STORE / android/keystore.properties). Not replacing it."; exit 1
fi
PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
keytool -genkeypair -v -keystore "$STORE" -alias attendpro -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass "$PASS" -keypass "$PASS" -dname "CN=AttendPro, O=Techmiary Technology Concepts, C=NG" >/dev/null
umask 077
cat > keystore.properties <<PROPS
storeFile=$STORE
storePassword=$PASS
keyAlias=attendpro
keyPassword=$PASS
PROPS
echo "✓ Upload key: $STORE"
echo "✓ Passwords:  mobile/android/keystore.properties"
echo "  Back up BOTH files somewhere safe (e.g. a password manager or encrypted drive)."
