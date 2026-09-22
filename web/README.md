# GameRater — Web App (Cloudflare Pages + Firebase)

The web version of GameRater. Same look and feel as the desktop app, but
multi-user: each person signs in, keeps their own game log, rates games into
tiers / GOTY awards, and refreshes from their Backloggd profile on demand.

## Architecture

```
Cloudflare Pages (this repo, auto-deployed from GitHub)
  public/                     static SPA
    index.html                launcher shell (login + sidebar + rater iframe)
    rater.html + rater.css    the rater view (tier / list / GOTY), CSS-isolated
    js/rater.js               data-driven rater (ported from the desktop template)
    js/{firebase,auth,store,launcher}.js
  functions/api/
    refresh.js                verifies Firebase token → triggers GitHub scrape
    cover.js                  same-origin cover-image proxy (for PNG export)

Firebase        Auth (Google + email/password) + Firestore (per-user data)
GitHub Actions  scraper/scrape.py runs Playwright on demand, writes Firestore
```

Data model (Firestore):
```
users/{uid}              { config: {folder_url, master_url}, status: {...} }
users/{uid}/data/games   { games: [ {title,rating,review,url,year_played,
                                      release_year,cover,categories[]}, ... ] }
```
Security rules (`../firestore.rules`) restrict each user to their own `users/{uid}` subtree.

## One-time external setup

### 1. Firebase
1. Create a project at <https://console.firebase.google.com>.
2. **Build → Authentication → Get started** → enable **Google** and **Email/Password**.
3. **Build → Firestore Database → Create database** (production mode).
4. Publish the security rules from this repo:
   ```
   npm i -g firebase-tools && firebase login
   firebase deploy --only firestore:rules --project <your-project-id>
   ```
   (or paste `firestore.rules` into the console → Firestore → Rules → Publish).
5. **Project settings → General → Your apps → Web app** → register an app, copy the
   config object into `public/js/firebase-config.js` (replace every `REPLACE_ME`).
   These values are public identifiers, not secrets.
6. **Project settings → Service accounts → Generate new private key** → download the
   JSON. You'll add it to GitHub in step 3.
7. Add your Cloudflare Pages domain under **Authentication → Settings → Authorized domains**.

### 2. GitHub token (lets Cloudflare trigger the scraper)
Create a **fine-grained personal access token** scoped to this repo with
**Actions: Read and write**. Save it for step 4.

### 3. GitHub Actions secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `FIREBASE_SERVICE_ACCOUNT` = the entire service-account JSON from step 1.6.

### 4. Cloudflare Pages
1. **Workers & Pages → Create → Pages → Connect to Git**, pick this repo.
2. Build settings:
   - **Root directory:** `web`
   - **Build command:** `npm install`
   - **Build output directory:** `public`
3. **Settings → Environment variables** (Production + Preview):
   - `FIREBASE_PROJECT_ID` = your Firebase project id
   - `GITHUB_REPO` = `owner/name` of this repo
   - `GITHUB_TOKEN` = the token from step 2 (mark as **encrypted**)
   - `GITHUB_REF` = your default branch (optional; defaults to `main`)
4. Deploy. Each push to the connected branch redeploys automatically.

### 5. (Optional) Seed your existing data
Migrate the desktop app's `games.csv` into your account:
```
cd ..   # repo root
FIREBASE_SERVICE_ACCOUNT="$(cat path/to/service-account.json)" \
  python scraper/seed_from_csv.py <your-uid> games.csv web/public/covers
```
(Your uid is shown in Firebase console → Authentication → Users after you sign in once.)

## Local development
```
cd web
npm install
# put real values in public/js/firebase-config.js first
npm run dev            # wrangler pages dev — serves static site + Functions
```
Auth and Firestore talk to your real Firebase project. The scrape button needs the
Cloudflare env vars set (`wrangler pages dev` reads them from a local `.dev.vars`
file if present); without them, viewing/rating/exporting still work.
