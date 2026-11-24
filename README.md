# AttendPro — QR Attendance System
*by Techmiary Technology Concepts*

Organisations and schools register their staff/students. Each person signs in to their portal with an **ID + password**, scans the **live QR code at reception**, and their attendance is recorded instantly with the time. Admins see it live, correct entries, and download or save reports (Excel / CSV).

## Quick start

```bash
git clone https://github.com/Dev-Samuel-Jeremiah/attendpro.git
cd attendpro
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # optional: demo school with 30 days of data
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000
- Demo admin: **DEMO-0001 / admin123**
- Demo staff: **DEMO-0002 / staff123**
- Or click **Create an organisation account** to start fresh.

## How it works

1. **Admin registers the organisation.** They get the first ID, e.g. `TMY-0001`.
2. **Admin registers members** one at a time or by CSV import. IDs (`TMY-0002`, `TMY-0003`, ...) and passwords are generated automatically and shown on printable login slips.
3. **Reception screen:** open *Settings → Reception QR screen* on the computer or TV at the entrance and leave it full-screen. The QR changes every 30 seconds (you can change this), so a photo of it stops working quickly.
4. **Member scans:**
   - in the portal, tap **Scan** and point the camera at the code; or
   - point the phone's normal camera at the code and tap the link. If they're not signed in yet, the scan is held for 3 minutes while they sign in.
5. **First scan of the day is check-in**; it's marked *On time* or *Late* using the start time and grace period. **The next scan is check-out**, and hours worked are calculated. Scans within 5 minutes of the last one are ignored as duplicates.

## Plans
| | Basic (free) | Professional | Enterprise |
|---|---|---|---|
| Staff accounts | 10 | 25 | Unlimited |
| Clock-in button (only at your premises), dashboard, history | ✓ | ✓ | ✓ |
| QR attendance, advanced reports, Excel/CSV export, self-service | | ✓ | ✓ |
| Leave management, PDF export, in-app + email notifications | | ✓ | ✓ |
| Custom branding (logo), audit trail, priority support | | | ✓ |
| Multiple branches, GPS geofencing on every scan, advanced analytics | | | ✓ |
| Face verification, payroll and payslips, weekly backups and 30-day restore | | | ✓ |

Prices, limits and features are edited by the platform super admin under `/platform/`; the
public pricing page is `/pricing/`. Paid plans are bought online through Paystack
(`PAYSTACK_SECRET_KEY`). Features not built yet show as *Coming soon*.

The app checks feature codes listed in `billing/catalog.py`; a plan without a feature locks
that page or button and points the admin to **Plan & billing**.

## Features
- Admin dashboard: present / late / not in / on site today, a 14-day chart, departments, live scan feed
- Daily attendance view. Scanned clock-in/out times are locked: nobody can change or delete them; administrators can only mark a day with no scan as leave/excused or absent, and add comments
- Reports for any date range, with presets and a department filter: attendance %, late count, absences, total hours, average arrival time, and a colour-coded daily register
- **Downloads:** Excel (3 sheets: Summary, Daily register, Time log) and CSV
- **Saved reports library:** save a report and download it again later
- Scan log with IP addresses (an audit trail of every attempt, including rejected ones)
- Member portal: today's status, monthly attendance ring, history with CSV export, password change
- Several organisations on one server, each kept fully separate
- Works offline on a local network: no CDN; the QR scanner library is bundled

## Phone camera & HTTPS (important)
Browsers only allow the **in-page camera scanner** on `https://` or `localhost`. On a local Wi-Fi setup over plain `http://192.168.x.x`, members can still use their **phone's built-in camera app**, which opens the link in the QR and records attendance. For the in-page scanner, serve over HTTPS (e.g. Caddy or nginx with a certificate, or a domain in production).

Set the address that gets encoded in the QR if needed:
```bash
export ATTENDPRO_PUBLIC_URL=https://attend.yourdomain.com
```

## Production
Settings are read from a `.env` file next to `manage.py`; copy [`.env.example`](.env.example) to start.
Production uses PostgreSQL (`DB_ENGINE=postgresql`); without a `.env` the app runs on SQLite in debug mode for local development.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | **Required with debug off.** A long random value (it also signs the QR codes) |
| `DJANGO_DEBUG` | `False` in production |
| `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` | your domain, e.g. `attendpro.cloud` / `https://attendpro.cloud` |
| `DJANGO_ADMIN_URL` | hard-to-guess path for the platform super-admin (default `django-admin/`) |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `ATTENDPRO_PUBLIC_URL` | address encoded in the reception QR |

The full server setup (Gunicorn, Nginx, HTTPS, daily backups) is in [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

## Android & iPhone apps
Native apps that open the live site, so every deploy reaches them instantly; see [`mobile/PUBLISHING.md`](mobile/PUBLISHING.md).

## Project layout
```
attendpro/        settings, urls
deploy/           Gunicorn, systemd, Nginx, backup and update scripts + DEPLOY.md
mobile/           Android & iPhone apps (Capacitor shells around the live site) + PUBLISHING.md
core/models.py    Organisation, User (ID login), Department, AttendanceRecord, ScanLog, SavedReport
core/services.py  rotating QR tokens, check-in/out logic, report calculations, Excel/CSV export
core/views.py     auth, kiosk, scanning, member portal, admin pages
billing/          plans, features, Paystack payments, platform super-admin pages
templates/        manage/ (admin), staff/ (member portal), kiosk/, auth/
static/           css/app.css, vendor/html5-qrcode.min.js
```
