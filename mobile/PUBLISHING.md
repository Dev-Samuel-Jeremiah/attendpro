# AttendPro for Android and iPhone

The apps are native shells that open **https://attendpro.cloud/app/** in a full-screen native web
view. Everything people see and use comes from the website.

## How updates work (read this first)

| You change… | Do people need to update or reinstall the app? |
|---|---|
| Any page, feature, fix, price, plan, wording, CSS or JavaScript, then deploy with `deploy/update.sh` | **No.** It's in the apps on the next page load. |
| `static/js/app-bridge.js` (back button, downloads, print, vibration, update prompt) | **No.** It's served by the website too. |
| The app icon, app name, splash screen, a new phone permission or native plugin, the Capacitor version | **Yes.** Build a new version and upload it to the stores (rare). |

When you release a new native version and want everyone on it, set `APP_MIN_VERSION` in the
server's `.env` (e.g. `APP_MIN_VERSION=1.1.0`) and `APP_IOS_URL` / `APP_ANDROID_URL` to the store
pages. Older apps then show an **Update needed** screen with a button to the store.

## What the app adds to the website

- **Opens straight to sign-in** (or the dashboard if already signed in), not the marketing page.
- **QR scanning and check-in selfies** with the phone camera; **GPS clock-in** with the phone's location.
  The phone asks permission first, in AttendPro's own words.
- **Downloads**: on Android, reports, payslips and backups go to the Downloads folder. On iPhone they
  open the share sheet (Save to Files, WhatsApp, Print…).
- **Print** buttons work (the phone's print dialog / Save as PDF).
- **Android back button** goes back a page; **iPhone**: swipe from the left edge.
- A short **vibration** when a clock-in succeeds or is refused.
- **Paystack** payments stay inside the app. WhatsApp, email, phone and map links open the right app.
- **Offline screen** with *Try again* when there's no internet; branded **splash screen** and icon.

## Settings: `mobile/app.settings.json`

| Setting | What it is |
|---|---|
| `version`, `build` | The version people see (1.0.0) and the store build number. **Raise `build` by 1 for every store upload.** |
| `siteUrl` | Where the app opens. Leave as `https://attendpro.cloud/app/`. |
| `devUrl` | Only for testing against your own computer, e.g. `http://192.168.1.20:8000/app/`. **Must be empty for store builds** (the build scripts refuse otherwise). |

After changing it, run `npm run sync` in `mobile/`.

---

## Android (Google Play)

### Test on a phone
```bash
cd mobile
npm install            # first time only
npm run apk            # → android/app/build/outputs/apk/debug/app-debug.apk
```
Copy `app-debug.apk` to an Android phone (WhatsApp it to yourself, or USB) and open it to install
(allow "install unknown apps" when asked).

### Signing key (once)
```bash
bash scripts/make-keystore.sh
```
It creates `~/attendpro-upload.jks` and `mobile/android/keystore.properties` (passwords).
**Back up both files** (password manager or encrypted drive). Never commit them; `.gitignore`
already keeps them out of git.

### Build for the Play Store
1. In `app.settings.json` raise `build` (and `version` if you like).
2. `npm run release:android` → `android/app/build/outputs/bundle/release/app-release.aab`
   (also a signed `app-release.apk` you can share directly).

### Publish
1. Create a Google Play developer account (one-time US$25) at https://play.google.com/console.
2. **Create app** → name *AttendPro*, app, free. Package name: `cloud.attendpro.app`.
3. Fill in the store listing: short and full description, screenshots (take them on a phone),
   the 512 × 512 icon (`static/brand/mark-512.png`), a 1024 × 500 feature graphic.
4. **Privacy policy URL:** `https://attendpro.cloud/privacy/`.
5. **Data safety:** the app collects name, email/phone (optional), precise location (at clock-in only),
   photos (check-in selfies, Enterprise), and app activity (attendance). Data is encrypted in transit;
   people can ask for deletion (see the privacy policy).
6. **App access:** reviewers need a sign-in. Create a demo organisation and give them its admin ID and
   password under *App content → App access*.
7. Upload `app-release.aab` to **Internal testing** first, try it, then promote to **Production**.

---

## iPhone (App Store), without a Mac

iPhone apps can only be built on a Mac. **Codemagic** (https://codemagic.io) lends one; the recipe is
`codemagic.yaml` at the top of this repository (workflow **ios-release**).

1. **Apple Developer Program** (US$99/year): https://developer.apple.com/programs/
2. In **App Store Connect** → *Users and Access* → *Integrations* → *App Store Connect API*, create a
   key with **App Manager** access. Download the `.p8` file once and note the Issuer ID and Key ID.
3. In **Codemagic** → *Team settings* → *Integrations* → *Developer Portal*, add that key and name it
   exactly **AttendPro App Store key**.
4. In **Certificates, Identifiers & Profiles** (developer.apple.com), register the Bundle ID
   `cloud.attendpro.app`. In **App Store Connect** create the app with that Bundle ID.
5. In Codemagic add this GitHub repository, choose **ios-release**, and start a build. Codemagic
   creates the signing certificate and profile, builds, and uploads to **TestFlight**.
6. Install **TestFlight** on an iPhone to try it, then submit for review from App Store Connect with:
   - Privacy policy `https://attendpro.cloud/privacy/`, support URL `https://attendpro.cloud/contact/`
   - A demo sign-in for the reviewer (App Review Information)
   - Screenshots from an iPhone (6.7" and 6.5" sizes)

**About App Review:** Apple rejects apps that are "just a website". In the review notes, point out what
the app does natively: camera QR scanning, GPS clock-in, check-in selfies, native downloads and share
sheet, printing, haptics and an offline screen.

---

## Changing the icon or splash screen
Replace the images in `mobile/assets/` (`icon-only.png` 1024², `icon-foreground.png`,
`icon-background.png`, `splash.png` and `splash-dark.png` 2732²), then:
```bash
cd mobile && npm run assets && npm run sync
```
and build new versions for the stores (raise `build`).

## Useful commands (in `mobile/`)
| Command | Does |
|---|---|
| `npm run sync` | Apply `app.settings.json` and copy plugins into both native projects |
| `npm run apk` | Android test APK |
| `npm run release:android` | Signed Play Store bundle + APK |
| `npm run android` | Open in Android Studio (run on a phone or emulator) |
| `npm run assets` | Regenerate icons and splash screens |
