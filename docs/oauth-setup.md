# Google OAuth setup

ArchFlow supports signing in via Google using the standard OAuth 2.0
Authorization Code flow. The `Continue with Google` button on the login
screen kicks off the dance; when client credentials are not configured the
endpoints 503 and the button is effectively disabled.

## 1. Create an OAuth client in Google Cloud

1. Open <https://console.cloud.google.com> and select (or create) a project —
   e.g. `ArchFlow`.
2. Left menu → **APIs & Services** → **OAuth consent screen**:
   - **User Type:** External → **Create**.
   - Fill in the app name, support email, developer contact.
   - **Application home page:** `https://archflow.tools`
   - **Application privacy policy link:** `https://archflow.tools/privacy`
   - **Application terms of service link:** `https://archflow.tools/terms`
   - **Scopes:** add `.../auth/userinfo.email`,
     `.../auth/userinfo.profile`, and `openid`. Nothing else is needed.
   - **Test users:** while the app is in testing mode, add every email you
     want to be able to sign in. Click **Publish app** later to skip this.
3. Left menu → **APIs & Services** → **Credentials** → **+ Create
   Credentials** → **OAuth client ID**:
   - **Application type:** Web application.
   - **Name:** e.g. `ArchFlow Web`.
   - **Authorized JavaScript origins:**
     - `https://archflow.tools`
     - `http://localhost:5173` *(dev)*
   - **Authorized redirect URIs:**
     - `https://archflow.tools/api/v1/auth/oauth/google/callback`
     - `http://localhost:8000/api/v1/auth/oauth/google/callback` *(dev)*
4. Copy the **Client ID** and **Client Secret**.

## 2. Wire the credentials into the backend

Google credentials are runtime secrets — they live in the backend's `.env`,
never in git.

### Production (`/srv/archflow/.env`)

```env
GOOGLE_CLIENT_ID=<from-google-console>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<from-google-console>
GOOGLE_REDIRECT_URI=https://archflow.tools/api/v1/auth/oauth/google/callback
FRONTEND_URL=https://archflow.tools
```

Restart the backend container so it picks up the new env:

```bash
cd /srv/archflow
docker compose -f docker-compose.prod.yml up -d
```

### Local dev (`.env` at repo root)

```env
GOOGLE_CLIENT_ID=<from-google-console>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<from-google-console>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/oauth/google/callback
FRONTEND_URL=http://localhost:5173
```

Restart the backend — `make dev-backend` or `make dev`.

## 3. Verify

1. Open the login page (`/login`).
2. Click **Continue with Google**. You should be redirected to
   `accounts.google.com`, not back to a stub prompt.
3. After granting consent, Google 302s back to the backend callback; the
   backend 302s to `<FRONTEND_URL>/auth/callback` with tokens in the URL
   fragment; the SPA consumes them and drops you at the home page.
4. Check the resulting user in Postgres:

   ```sql
   select id, email, name, auth_provider from users where auth_provider = 'google';
   ```

## 4. Flow recap (for debugging)

```
user → [Continue with Google]
     → GET /api/v1/auth/oauth/google/login
        → 302 https://accounts.google.com/o/oauth2/v2/auth?...
user grants consent
     ← 302 <GOOGLE_REDIRECT_URI>?code=...
     → GET /api/v1/auth/oauth/google/callback?code=...
        → POST https://oauth2.googleapis.com/token            (exchange)
        → GET  https://www.googleapis.com/oauth2/v2/userinfo  (fetch profile)
        → upsert User (+ personal workspace on first sign-in)
        → 302 <FRONTEND_URL>/auth/callback#access_token=...&refresh_token=...
SPA /auth/callback reads the fragment, stores tokens, navigates home.
```

## 5. Disabling OAuth

Leave `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` blank in `.env`. Both
endpoints will return HTTP 503. The frontend doesn't currently hide the
button based on this — tapping it just lands on a 503 page — follow-up
work is to have the SPA probe for OAuth availability on load.

## 6. Rotating the client secret

If the secret leaks (or you want to rotate proactively):

1. Google Console → **Credentials** → open the OAuth client.
2. Under **Client secrets** → **+ Add secret**.
3. Paste the new secret into both `.env` files (prod + local), restart the
   backend.
4. When you've confirmed sign-in still works, return to the console and
   **delete the old secret**.

No code changes required; the whole swap is a single env-var update.

## 7. Troubleshooting

| Symptom                                        | Most likely cause                                                                          |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Button click → 503                             | `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` empty in the backend's `.env`.                |
| Google shows `redirect_uri_mismatch`           | The exact callback URL is not in **Authorized redirect URIs** — it must match byte-for-byte. |
| `Error 403: access_denied` after consent       | App is in testing mode and your email isn't in the test-users list. Add it or publish.     |
| Callback succeeds but SPA stays on `/auth/callback` | `FRONTEND_URL` is wrong, or JS is disabled. Check browser devtools for errors.         |
| Tokens appear in URL bar after sign-in         | Expected briefly; the SPA wipes the fragment on mount. If it sticks, `AuthCallback` isn't mounting — check the route exists in `App.tsx`. |
