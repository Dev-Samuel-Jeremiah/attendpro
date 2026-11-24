# Publishing AttendPro on Google Play

Everything Google asks for, in the order Play Console asks for it. Copy the text blocks as they are.

## What's ready

| Item | File | Google's requirement |
|---|---|---|
| App bundle | `mobile/android/app/build/outputs/bundle/release/app-release.aab` (also in `~/AttendPro-PlayStore/`) | Signed .aab, target API 35+ (ours: 36) |
| App icon | `mobile/store/icon-512.png` | 512 × 512 PNG, under 1 MB |
| Feature graphic | `mobile/store/feature-graphic-1024x500.png` | 1024 × 500 PNG/JPG |
| Phone screenshots | `mobile/store/screenshots/01…08` | 2 to 8, 9:16 (1080 × 1920) |
| Privacy policy | https://attendpro.cloud/privacy/ | Public URL |
| Account deletion | https://attendpro.cloud/account/delete/ | Public URL + path inside the app |
| Reviewer sign-in | `python manage.py create_review_account` on the server | Working credentials |

Version in this bundle: **1.1.0 (version code 2)**. Every later upload needs a higher build number:
raise `"build"` (and `"version"`) in `mobile/app.settings.json`, then run `npm run release:android` in `mobile/`.

---

## Important: personal accounts must test first

Your developer account is a **personal** account. Google requires personal accounts created after
13 November 2023 to run a **closed test with at least 12 testers who stay opted in for 14 days in a row**
before you can apply for production (public) release. Plan for about 3 weeks:

1. Set up the app and store listing (steps 1–4 below).
2. Upload the bundle to **Closed testing** and invite 12+ testers (step 5).
3. Wait 14 days with at least 12 testers opted in.
4. **Apply for production access** from the Dashboard, then release to everyone (step 6).

Good testers: your own staff, friends and early customers with Android phones and Gmail addresses.

---

## 1. Create the app

Play Console → **Create app**

- App name: `AttendPro: Staff Attendance`
- Default language: English (United Kingdom), or English (United States)
- App or game: **App**
- Free or paid: **Free** (this cannot be changed later; plans are paid on the website)
- Tick both declarations → **Create app**

## 2. Store listing (Grow users → Store presence → Main store listing)

**App name** (30 max)
```
AttendPro: Staff Attendance
```

**Short description** (80 max)
```
Clock in with one tap or a QR scan. Live attendance, leave and payroll.
```

**Full description** (4000 max)
```
AttendPro is the simple, reliable way for schools and organisations to record attendance, right from the phones people already carry.

CLOCK IN WITH ONE TAP
Staff and students tap Clock in. AttendPro checks they are really at work using their phone's location, then records the exact time. No paper registers, no queues, no buddy-punching.

OR SCAN THE RECEPTION QR
Put AttendPro's QR code on a screen at your entrance. People scan it with the app and are checked in within seconds.

SEE YOUR WHOLE TEAM, LIVE
Administrators get a live dashboard: who is in, who is late, who hasn't arrived and who is on site right now, with a 14-day trend, arrival-time patterns and a punctuality ranking.

FOR EVERYONE WHO CLOCKS IN
• Today's check-in and check-out times, and time on site
• This week at a glance, attendance rate, on-time streak and hours
• Full attendance history
• Leave requests and approvals
• Payslips worked out from attendance (Enterprise)
• Notifications for approvals and reminders

FOR ADMINISTRATORS
• Add people one by one or import a spreadsheet
• Daily attendance, reports and Excel, CSV and PDF exports
• Late arrivals, absences and leave in one place
• Multiple branches, each with its own location and QR screen
• Face check at clock-in (optional)
• Audit trail of every attempt, including refused ones
• Clock-in times can't be edited, so records stay trustworthy

PRIVATE AND SECURE
Location is only checked at the moment someone clocks in; AttendPro never tracks people in the background. Each organisation's data is kept separate and all connections are encrypted.

PLANS
Start free for up to 10 people. Upgrade to Professional or Enterprise in naira whenever you're ready. Plans never renew automatically.

Your organisation's administrator gives you your sign-in ID. Setting up a new organisation? Choose "I'm setting up my organisation" when you open the app.

AttendPro is made by Techmiary Technology Concepts.
```

**Graphics**
- App icon: `icon-512.png`
- Feature graphic: `feature-graphic-1024x500.png`
- Phone screenshots: all 8 files in `screenshots/`, in number order
- Tablet screenshots: optional; skip for now

**Contact details** (Store settings → Store listing contact details)
- Email: your support email (required, shown publicly)
- Website: `https://attendpro.cloud`
- Phone: optional

**Category** (Store settings → App category)
- App: **Business**
- Tags: Attendance, Productivity, Business

## 3. App content (Policy → App content)

Answer every section until each shows a green tick.

**Privacy policy**
```
https://attendpro.cloud/privacy/
```

**Ads**: No, my app does not contain ads.

**App access**: All or some functionality is restricted → **Add instructions**. First create the review
accounts on the server (see "Reviewer accounts" at the end), then paste:
```
Name: AttendPro review accounts
Administrator: REVIEW-0001 / <password printed by the command>
Staff member:  REVIEW-0002 / <password printed by the command>

1. Open the app, swipe through the welcome screens and choose "I'm joining my team".
2. Sign in with either account. The administrator sees the live dashboard, members, reports, leave and payroll. The staff member sees their attendance, history and leave.
3. Clock in only works within 5 km of the organisation's location (Jos, Nigeria), by design: it confirms people are at work. Everything else can be reviewed from anywhere.
```

**Content rating**: Start questionnaire
- Email: your email. Category: **All other app types**
- Violence, sexuality, language, drugs, gambling, etc.: **No** to all
- Does the app allow users to interact or exchange content? **No**
- Does the app share the user's current location with other users? **Yes** (administrators can see where a clock-in happened)
- Does the app allow users to purchase digital goods? **Yes** (organisation plans)
- Expected result: rated for everyone (3+ / PEGI 3), with "Shares location" and "In-app purchases" notes.

**Target audience and content**
- Age groups: **13–15, 16–17, 18 and over** (do not select under 13)
- Appeals to children? **No**

**News app**: No. **COVID-19 tracing**: No. **Government app**: No.
**Financial features**: My app doesn't provide any financial features. **Health**: No health features.

**Advertising ID**: No, the app does not use advertising ID.

**Data safety**: answer as follows.

Data collection and security
- Does your app collect or share any of the required user data types? **Yes**
- Is all data encrypted in transit? **Yes**
- Account creation: **Username and password**
- Delete account URL: `https://attendpro.cloud/account/delete/`
- Can users request that some data is deleted without deleting their account? **Yes**

Data types (for each: **Collected: Yes**, **Shared: No**, **Processed ephemerally: No**):

| Data type | Required or optional | Purposes |
|---|---|---|
| Location → Precise location | Required | App functionality, Fraud prevention, security and compliance |
| Personal info → Name | Required | App functionality, Account management |
| Personal info → Email address | Optional | App functionality, Account management, Developer communications |
| Personal info → Phone number | Optional | App functionality, Account management |
| Personal info → User IDs | Required | App functionality, Account management |
| Personal info → Other info (job title, department) | Optional | App functionality |
| Financial info → Purchase history (organisation plan payments) | Optional | App functionality, Account management |
| Financial info → Other financial info (bank details for payroll) | Optional | App functionality |
| Photos and videos → Photos (check-in selfies, if the organisation uses face checks) | Optional | App functionality, Fraud prevention, security and compliance |
| App activity → Other user-generated content (leave reasons, comments) | Optional | App functionality |

Card details are entered on Paystack's own payment page and never reach AttendPro.
"Shared" is No because Paystack and our hosting provider act on our behalf (service providers), which Google doesn't count as sharing.

## 4. Pricing and countries

- Monetise → Products: nothing to set (the app itself is free; plans are paid on the website through Paystack).
- Release → Production → Countries/regions: add **Nigeria**, plus any other countries you serve. Do the same for the closed test track.

## 5. Closed test (the 14 days)

1. Testing → **Closed testing** → Create track (or use "Closed testing – Alpha") → **Manage track**.
2. Testers tab → **Create email list** → add at least 12 Gmail addresses → Save. Copy the **opt-in link**.
3. Releases → **Create new release**.
   - **Play App Signing**: accept *Google-generated key* (recommended). Your `~/attendpro-upload.jks` stays the **upload key**; keep it and `mobile/android/keystore.properties` backed up.
   - Upload `app-release.aab`.
   - Release name: `1.1.0 (2)`
   - Release notes:
     ```
     <en-GB>
     First release of AttendPro for Android: one-tap clock-in with precise GPS, reception QR scanning, live dashboards, leave and payslips.
     </en-GB>
     ```
4. **Review release** → **Start rollout to Closed testing**. Google reviews it (hours to a few days).
5. Send testers the opt-in link. Each tester opens it, taps **Become a tester**, then installs AttendPro from Play.
   They must stay opted in for 14 days. Ask them to open the app now and then; Google asks about tester engagement when you apply.

## 6. Production

After 14 days: Dashboard → **Apply for production** → answer the questions about your test
(who tested, what feedback you got, what you changed). Once approved:
Release → Production → Create new release → **Add from library** (pick the tested bundle) → roll out.

When AttendPro is live, put its Play address into the server's `.env` so the app's
"Update needed" prompt sends people to Play (and ask Claude to switch the website's
"Get the app" page from the GitHub download to a Get it on Google Play button):
```
APP_ANDROID_URL=https://play.google.com/store/apps/details?id=cloud.attendpro.app
```

## Reviewer accounts

On the server:
```
sudo -u attendpro -H bash -c 'cd /srv/attendpro/app && source ../venv/bin/activate && python manage.py create_review_account'
```
It creates "AttendPro Review" (code REVIEW, Enterprise, 12 people, 30 days of sample attendance, 5 km radius)
and prints two passwords. Run it with `--reset` for new passwords. Remove the organisation from
Platform → Organisations if you ever stop needing it.

## Good to know

- **People who installed the APK from GitHub**: Play re-signs apps with Google's key, so the GitHub
  APK and the Play version can't update each other. Those people should uninstall the GitHub APK
  and install from Play. After launch, point everyone to Play instead of GitHub.
- **Website changes still reach the app instantly.** You only upload a new bundle when the native
  shell changes (new plugin, icon, version).
- **Permissions**: the app asks for Camera (QR and selfies) and Location (while clocking in only).
  No background location, so no extra permission declaration is needed.
