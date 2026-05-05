# Setup Guide — Supabase + Vercel + Railway

The code is wired up. Follow these steps to bring auth and deployment online.  
Estimated time: **30–45 minutes**.

---

## 1. Supabase (Auth + Database)

### 1.1 Create the project
1. Go to **https://supabase.com** → sign in with GitHub
2. Click **New project**
3. Pick a name (e.g. `sonicly`), set a strong DB password (save it), choose the region closest to your users
4. Wait ~2 minutes while the project provisions

### 1.2 Grab your API keys
Open **Project Settings → API**. Copy these two values:
- **Project URL** → `VITE_SUPABASE_URL`
- **anon / public key** → `VITE_SUPABASE_ANON_KEY`

Also copy the **JWT Secret** from **Project Settings → API → JWT Settings** → `SUPABASE_JWT_SECRET` (used by the backend).

### 1.3 Set local env vars
```bash
cd frontend
cp .env.example .env
# Then paste your Supabase values into .env

cd ../backend
cp .env.example .env
# Paste your SUPABASE_JWT_SECRET into .env
```

### 1.4 Enable email auth
**Authentication → Providers → Email** → enable. (On by default.)

For dev, **disable "Confirm email"** under **Authentication → Providers → Email** so you can sign up without inbox verification. Re-enable for production.

### 1.5 Enable Google login
1. Go to **https://console.cloud.google.com** → create a project
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
3. App type: **Web application**
4. Authorized redirect URIs: `https://YOUR_PROJECT_REF.supabase.co/auth/v1/callback`  
   (find your project ref in your Supabase URL)
5. Copy the **Client ID** and **Client Secret**
6. Back in Supabase: **Authentication → Providers → Google** → toggle on, paste both, save

### 1.6 Enable Facebook login
1. Go to **https://developers.facebook.com/apps** → **Create App** → "Consumer"
2. Add **Facebook Login** product
3. **Settings → Basic** → copy **App ID** + **App Secret**
4. **Facebook Login → Settings** → Valid OAuth Redirect URIs:  
   `https://YOUR_PROJECT_REF.supabase.co/auth/v1/callback`
5. Back in Supabase: **Authentication → Providers → Facebook** → toggle on, paste both, save

### 1.7 (Optional) Apple login
⚠️ **Apple requires a paid Apple Developer account ($99/year).** Skip for now if you're just testing.  
Full guide: https://supabase.com/docs/guides/auth/social-login/auth-apple

### 1.8 Test it locally
```bash
cd frontend && npm run dev
```
Visit http://localhost:3000/signup → click "Continue with Google" → should redirect, log you in, drop you on `/dashboard`.

---

## 2. Vercel (Frontend Hosting)

### 2.1 Push your code to GitHub
```bash
cd "/Users/jaymakwana/AI Audio Editor"
git init
git add .
git commit -m "Initial Sonicly setup"
gh repo create sonicly --private --source . --push
# Or create the repo on github.com manually and push
```

### 2.2 Deploy
1. Go to **https://vercel.com** → sign in with GitHub
2. **Add New → Project** → import the `sonicly` repo
3. **Root directory:** click "Edit" → select `frontend`
4. Framework preset: **Vite** (auto-detected)
5. **Environment Variables** → add:
   - `VITE_SUPABASE_URL` = your Supabase URL
   - `VITE_SUPABASE_ANON_KEY` = your Supabase anon key
   - `VITE_API_URL` = (leave blank for now — fill after Railway is set up)
6. Click **Deploy**

Vercel gives you a URL like `https://sonicly-xyz.vercel.app`. Save it.

### 2.3 Add the Vercel URL to Supabase
**Authentication → URL Configuration** → add `https://sonicly-xyz.vercel.app` to:
- **Site URL**
- **Redirect URLs** (add `https://sonicly-xyz.vercel.app/**`)

Otherwise OAuth redirects will fail in production.

---

## 3. Railway (Backend Hosting)

### 3.1 Deploy
1. Go to **https://railway.app** → sign in with GitHub
2. **New Project → Deploy from GitHub repo** → pick `sonicly`
3. Railway will detect both `frontend` and `backend` — click **Settings** on the service and set:
   - **Root Directory:** `backend`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT` (already in `railway.json`)
4. **Variables** tab → add:
   - `SUPABASE_JWT_SECRET` = your JWT secret
   - `ALLOWED_ORIGINS` = `https://sonicly-xyz.vercel.app,http://localhost:3000`
5. **Settings → Networking → Generate Domain** to get a public URL (e.g. `sonicly-api.up.railway.app`)

### 3.2 Wire the frontend to the backend
Back in **Vercel → Settings → Environment Variables**:
- `VITE_API_URL` = `https://sonicly-api.up.railway.app/api`
- Click **Redeploy** so the change takes effect

### 3.3 Verify
```bash
curl https://sonicly-api.up.railway.app/api/health
# → {"status":"ok","service":"sonicly-api"}
```

---

## 4. You're done ✓

| Layer | Lives at |
|---|---|
| Frontend | `https://sonicly-xyz.vercel.app` |
| Backend | `https://sonicly-api.up.railway.app` |
| Auth + DB | `https://YOUR_PROJECT_REF.supabase.co` |

**What works now:**
- ✅ Google / Facebook (and Apple if configured) social login
- ✅ Email + password sign-up & login
- ✅ Protected `/dashboard`, `/processing`, `/editor` routes
- ✅ Sign out from the sidebar user menu
- ✅ Backend verifies Supabase JWTs on every request

**Cost so far:** $0/month (everything fits in free tiers).

---

## Common gotchas

| Symptom | Fix |
|---|---|
| OAuth redirects you to a 404 | Add the Vercel URL to Supabase **URL Configuration → Redirect URLs** |
| Login works locally but not on Vercel | Env vars not set on Vercel — go to project Settings → Environment Variables |
| Backend returns 401 on every request | `SUPABASE_JWT_SECRET` mismatch between Supabase and Railway |
| CORS errors in browser console | Add the Vercel URL to backend `ALLOWED_ORIGINS` env var on Railway |
| `VITE_*` env vars look unchanged | Vite bakes them at build time — redeploy after changing them |

## Next steps when you're ready
- Replace in-memory `_users` / `_projects` lists in the FastAPI routers with Supabase Postgres tables
- Add a `projects` table in Supabase: `id, user_id, name, duration, status, created_at, updated_at`
- Wire real audio processing (AssemblyAI for transcription, Dolby.io for noise removal, Claude API for the chat assistant)
