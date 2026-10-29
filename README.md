# Aisomedo

**From instant captured media to Instagram Reels. You stay in control.**

Aisomedo helps a class administrator turn photos and videos into branded Instagram Reels. Collect media, choose the order and video sections, review the result, then approve publication. A schedule helps you stay on track. It never replaces your approval.

![Aisomedo dashboard with an active package and a review ready to open](web/public/promotion/web/dashboard.png)

## Why Aisomedo?

- **One place to prepare a post.** Media, editing, branding, captions, and review belong to the same publishing flow.
- **Keep your style.** Add your logo and optional opening and closing cards to a vertical Reel.
- **Keep the final decision.** Approve, skip, or reschedule a review. Opening a preview does not publish it.
- **Keep a clear history.** A package is completed only after Instagram confirms publication. You can view past packages and activity.
- **Use web and Android.** Pair trusted browsers and phones with one-time codes. There are no passwords or user roles; paired clients have equal access.

This is a self-hosted project under active development, not a managed social media service. No measured productivity claims are made.

## Start locally on Windows

Install **Git, PowerShell, and Docker Desktop**; start Docker's Linux container engine. The stack uses **Node.js 26.13.0/npm, React 19.3.1, TypeScript, Vite; Python 3.12/uv, FastAPI/Uvicorn; PostgreSQL 18, SQLAlchemy, psycopg, Alembic; FFmpeg/ffprobe, Pillow/pillow-heif; Caddy 2; Cryptography/Fernet, HTTPX, and the Meta Instagram API**. Docker installs these runtime/build dependencies; host Node is only needed for web development. Android (Kotlin/Jetpack Compose) and Firebase/FCM are optional.

1. Run in PowerShell (skip the first two lines if already in the repository):

   ```powershell
   git clone https://github.com/35HaRRy/aisomedo.git
   Set-Location aisomedo
   powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start-local.ps1 -PairingCode
   ```

2. On first startup, the script creates private **`ops/.env.local`** with the required initial values below. No manual credentials are needed for the local demo. If the file already exists, check these assignments; the script preserves existing values and only adds a missing encryption key.

   | Required setting | Initial local value |
   | --- | --- |
   | `POSTGRES_PASSWORD` | Automatically generated database password |
   | `SIGNED_URL_SECRET` | Automatically generated signing secret |
   | `META_TOKEN_ENCRYPTION_KEY` | Automatically generated Fernet key; shared by API/worker |
   | `PUBLIC_BASE_URL`, `PUBLIC_HTTPS_ORIGIN` | Both `http://localhost:9081` |
   | `COOKIE_SECURE` | `false` for local HTTP only |

   Keep secrets stable and private; never commit this file or put secrets in `VITE_*`. Compose supplies `DATABASE_URL`; do not add a host database URL.

3. Open **http://localhost:9081**, choose **Uygulamayı aç**, then enter the printed one-time code and a browser name to **Eşleştir**.
4. For rendering/scheduling, opt in separately and type `START` when prompted:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start-local.ps1 -StartWorker
   ```

   Keep the test plan disabled: a configured worker can publish after approval. Real Instagram publishing requires a professional account, an Instagram Login token with publishing permissions, and publicly reachable HTTPS media URLs; localhost is not sufficient. Browser OAuth currently uses a stub; use **Instagram erişim tokenı → Token ile bağlan** instead.

[Detailed Windows setup, environment/Meta settings, and native installation →](docs/guide/windows-local-setup.md) · [Browser setup, restart/stop, and Android connection →](docs/guide/getting-started.md)

## A simple publishing flow

### 1. Upload and arrange your media

Open **Güncel Paket**. Expand **Fotoğraf ve video yükle** and select files. Wait until each file is accepted into the package. Then arrange the media and choose the video sections you want to keep.

![The active package, media cards, and saved Reel preview](web/public/promotion/web/package.png)

Save your edits before rendering. An empty video selection means “use the whole video,” not “remove the video.” [Detailed upload and editing guide →](docs/guide/publishing-a-reel.md#1-upload-media)

### 2. Prepare and review the Reel

Render the saved montage, then open the publication review from **Kontrol Paneli** when it is ready. Check both the Reel and its caption. Rendering a preview does not publish it.

![Publication review with the Reel, caption, and three decision options](web/public/promotion/web/review.png)

[Rendering, manual review, and schedule details →](docs/guide/publishing-a-reel.md#3-render-and-open-a-review)

### 3. Approve, or choose another time

Choose **Onayla ve yayınla** only when you want to publish, then confirm. Or use **Bu zamanı atla** / **Başka zamana planla**. A failed or uncertain send is not a completed publication; refresh and check the result before trying again.

After Instagram confirms success, find the package under **Tamamlanmış paketler**. [Decisions and completion →](docs/guide/publishing-a-reel.md#4-make-a-decision) · [Settings and recovery →](docs/guide/settings-and-recovery.md)

New-browser walkthroughs explain the important controls. Use **Tüm tanıtımları geç** to skip them all, or **Yardım → Tanıtımları yeniden başlat** to see them again. Tour preferences stay in that browser.

## Built with

| Part | Technology |
| --- | --- |
| Web workspace | React 19.3.1, TypeScript, Vite, Node.js 26.13.0 |
| Android client | Kotlin, Jetpack Compose |
| API | FastAPI |
| Domain and data | Python, SQLAlchemy, Alembic, PostgreSQL |
| Background work | Dedicated scheduler, FFmpeg rendering, Instagram publishing |
| Operations | Docker Compose, Caddy, GitHub Actions, signed Android releases |

Repository: `web/`, `android/`, `backend/`, `dojo-core/`, `worker/`, and `ops/`. See [domain terms](CONTEXT.md), [product design](docs/specs/dojo-reel-publishing-mvp.md).

For web development, install Node.js 26.13.0, then run `npm ci` and `npm run dev` inside `web/`. For checks, use `npm run typecheck`, `npm test`, `npm run build`, and `npm run test:browser`. The Python workspace uses Python 3.12 and `uv`; backend/domain/worker integration tests also need PostgreSQL through Docker and FFmpeg.

## Android app

Use the native Android client to upload media, follow your package, and open reviews from your phone.

- [Download signed APK · v0.2.0](https://github.com/35HaRRy/aisomedo/releases/download/android-v0.2.0/aisomedo.apk)
- [Download SHA-256 checksum](https://github.com/35HaRRy/aisomedo/releases/download/android-v0.2.0/aisomedo.apk.sha256)
- [All Android releases](https://github.com/35HaRRy/aisomedo/releases)

Download the APK to your phone, allow installation from that source when Android asks, and install it. Enter your installation’s **HTTPS server address**, then pair with a fresh one-time code. `localhost` on a phone is the phone itself, not your Windows computer. The local loopback-only demo above is not a phone-accessible HTTPS deployment.

[Android installation and connection steps →](docs/guide/getting-started.md#android-installation-and-connection)
