# DevVault

A multi-user, admin-moderated hackathon workspace. There is no public registration — one administrator (Sujal) creates every account. Everyone signs in with a username and password; projects and hackathons are shared/global, but normal users can only *propose* changes (submission/deletion requests) — the admin approves or rejects them.

This app is **independent** of the Chrome Extension (separate codebase, separate process, **never modified**) but connects to the **same Supabase project**.

---

## Access model

```
                     DEVVAULT
                        │
                      LOGIN (username + password, no sign-up)
                        │
              ┌─────────┴─────────┐
              │                   │
            ADMIN                USER
          (e.g. Sujal)
              │                   │
        Full management      Read + Request
              │                   │
      ┌───────┼────────┐          │
      │       │        │          │
   Users   Projects Hackathons    │
      │       │        │     ┌────┴─────┐
      │       │        │     │          │
      │       │        │  Add Request  Delete Request
      │       │        │     │          │
      │       │        │     └────┬─────┘
      │       │        │          │
      │       │        │        ADMIN approves/rejects
      │       │        │          │
      └───────┴────────┴──────────┘
                    │
              SHARED DATABASE → AI Chat / AI Matching
```

| Data | Scope | Normal user can | Admin can |
|---|---|---|---|
| Projects | **Global** — every active user sees every project | View, search, use in AI Chat/matching, export, **request** add/delete | Add/Edit/Delete directly, approve/reject requests |
| Hackathons | **Global** — every active user sees every hackathon | View, use in AI Chat/matching, **request** add | Add/Delete directly, approve/reject requests |
| Submission/deletion requests | **Private per submitter** | See only their own | See and act on everyone's |
| User accounts | **Admin-only** | — | Create, activate/deactivate, reset password, delete |

## What each page does

- **🏠 Dashboard** — Total Projects, Active Hackathons, Best Match Today (computed instantly, no AI call), Next Hackathon Ending. Admins additionally see a 🔔 pending-requests count broken down by type.
- **📂 Projects** — everyone sees every project (Title, Details, Repo Link, Live Link — deliberately only these four fields). Admin gets **+ Add Project** (inserts immediately) plus Edit/Delete. Normal users get the same form but the button reads **Submit for Approval**, and instead of a Delete button they get **Request Delete** with an optional reason.
- **🏆 Hackathons** — a global timeline (Name, Template/Photo, Starting Time, Ending Time, Registration Link, Prize Pool), status computed live (UPCOMING/ONGOING/ENDING SOON/ENDED), sorted chronologically. Same admin-direct vs. user-request split as Projects.
- **🤖 AI Chat** — grounded only in real Projects/Hackathons data, works with or without a Gemini key (falls back to the deterministic matching engine).
- **📥 Export** — Excel/CSV of all projects (Title, Details, Repo Link, Live Link), clickable hyperlinks in the Excel file.
- **⚙️ Settings** — tabs: **Account** (username/role, sign out), **Gemini API** (per-session key, Save/Clear), **My Requests** (status of everything you've submitted). Admins additionally get **User Management**, **Submission Requests**, and **Deletion Requests** tabs.

## Why this doesn't touch the Chrome Extension

The extension still writes to the exact same `projects` table it always has (title/problem_solved/description/tags/github_url/demo_url/devpost_url + user_id), completely unmodified. Two things changed only at the **database** level, not in the extension's code:

1. **`projects` is now admin-write-only via RLS.** Every active user can still read every project (global visibility), but only an admin session can INSERT/UPDATE/DELETE directly — normal users go through a submission request instead. This means the extension's "+ Add to DevVault" button keeps working exactly as before **when the browser is signed into an admin account** (e.g. Sujal's own account, since the extension was originally built as a personal tool). If a non-admin user were also signed into the extension, their save attempts would now be rejected by Postgres — a deliberate, documented consequence of "normal users cannot directly insert projects," not a bug.
2. **Devpost URL is no longer required.** The new minimal Projects form (Title/Details/Repo Link/Live Link) doesn't collect a Devpost URL at all, so that column was relaxed from `NOT NULL` to nullable. The extension's own writes are unaffected — it still always provides one.

The Chrome Extension's **`joined_hackathons`** table (private, per-user "hackathons I personally joined") remains completely separate from this app's global `hackathons` catalog — see `supabase/migrations/0005_global_hackathons.sql` for the original reasoning, which still holds.

## Authentication architecture

Supabase Auth is fundamentally email/password. To get a plain username+password login with **zero public registration**:

- Each account's real Supabase Auth email is a synthetic, reserved, never-emailed address: `{username}@devvault.internal`. Users never see or type this — they only ever enter a username.
- The `profiles` table (migration `0008`) carries the actual username, `role` (`admin`/`user`), and `status` (`active`/`inactive`). There is **no password column anywhere in this app's own tables** — Supabase Auth (GoTrue) stores passwords bcrypt-hashed in the protected `auth.users` table, never touched or duplicated here.
- **Only an admin can create accounts.** This requires the Supabase Auth Admin API, which requires the `service_role` key — see the next section for why that's safe here.
- A deactivated account is locked out at **two independent layers**: the login flow explicitly checks `profiles.status` right after a successful password check, *and* every RLS policy on every shared table requires `is_active_user()`, so even a still-valid session token from before deactivation loses access immediately, not just at next login.

## Why a service-role key is needed here (and why it's still safe)

A normal authenticated session — even an admin's own — can only manage its **own** Supabase Auth account through the client SDK. Creating a *brand-new* user, forcing *another* user's password, or deleting *another* user's auth record all require the Auth Admin API, which only the `service_role` key can call.

This key is read from a server-side environment variable (`SUPABASE_SERVICE_ROLE_KEY`) and used **exclusively** inside `services/admin_service.py`, for exactly three operations: create user, reset another user's password, delete user. Everything else — including activating/deactivating a user, which only touches `profiles.status` — goes through the ordinary anon-key client + RLS instead, to keep the service-role key's surface area as small as possible.

**This is safe specifically because it's a Streamlit app.** Streamlit scripts execute entirely on the server; the browser only ever receives rendered HTML/websocket deltas, never the Python process's environment variables. This is fundamentally different from the Chrome Extension, where any secret embedded in the bundle ships to and is inspectable by the browser — which is exactly why the extension (and this app's own anon-key usage) never touch a service-role key. If `SUPABASE_SERVICE_ROLE_KEY` isn't set, the app still runs fully; only create/reset-password/delete-user are disabled (with a clear in-app message), while everything else — including activate/deactivate — keeps working.

## Setting up the initial admin (Sujal)

There's a chicken-and-egg problem: only an admin can create users, but initially there is no admin. `scripts/bootstrap_admin.py` solves this — run it **once**, locally, after the migrations:

```bash
cd streamlit_app
SUPABASE_URL=https://your-project.supabase.co \
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key \
python scripts/bootstrap_admin.py
```

It interactively prompts for a username (default `sujal`) and password via `getpass()` — hidden input, never echoed to the terminal, never saved to shell history, never written into any file. It uses the exact same secure path (`services/admin_service.create_user`) the in-app "Create User" feature uses later. No password is ever hardcoded anywhere in this repo.

## Setup

### 1. Database migrations

Run these in the Supabase SQL Editor, **in order**. If `0001`–`0007` are already applied (from earlier phases), skip straight to `0008`:

| Migration | What it does |
|---|---|
| `0001`–`0004` | Extension's `projects` / `joined_hackathons` tables (Chrome Extension) |
| `0005`–`0007` | Global `hackathons` table + RLS + cleanup (earlier Streamlit phase) |
| `0008_profiles_and_roles.sql` | `profiles` table, `is_admin()`/`is_active_user()` helper functions |
| `0009_profiles_rls.sql` | RLS for `profiles` |
| `0010_projects_global_admin_rls.sql` | Makes `projects` globally readable, admin-write-only; relaxes `devpost_url` |
| `0011_hackathons_minimal_fields_admin_rls.sql` | Adds `registration_link`/`template_photo`; admin-write-only RLS |
| `0012_submission_and_deletion_requests.sql` | Request tables + RLS |
| `0013_hackathon_template_storage.sql` | *Optional* — enables photo upload (URL entry always works without it) |

Supabase will warn **"This query creates a table without enabling Row Level Security"** for `0005`/`0008`/`0012` since each migration creates its table before a *separate* migration enables RLS on it — click **"Run without RLS"** and then run the very next migration immediately afterward, which enables it.

### 2. Bootstrap the admin account

See "Setting up the initial admin" above.

### 3. Configure environment variables

```bash
cp .env.example .env
```

```
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-anon-public-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key   # optional; enables full user management
```

Never put a Gemini key here — see below.

### 4. Install and run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Sign in as the admin you bootstrapped. From **Settings → User Management**, create accounts for everyone else.

## Gemini API key

Each user enters their own key on **Settings → Gemini API** — kept only in `st.session_state` for that browser session, never written to Supabase or disk, never logged, never in `.env.example`. The app works fully without one; AI Chat and matching fall back to the deterministic engine.

## Gemini failure handling & matching engine

`services/gemini_service.py` retries 503/429/500/504/timeout/network errors up to 3 times with exponential backoff (2s, 4s, 8s), then raises `GeminiUnavailableError` rather than crashing — callers show *"⚠ Gemini is temporarily unavailable. Showing database-based recommendations"* and fall back to `services/matching_engine.py`, a deterministic 4-factor scorer (Name/Title similarity, Details/context similarity, hackathon template/context richness, Feasibility) that never calls any AI API. The match **score** always comes from this engine; Gemini, when reachable, only adds the "why it matches"/"missing features"/"suggested improvements" narrative on top.

## Intelligent routing

`agents/router.py` classifies each chat message with plain keyword rules (no LLM call spent on routing): simple listing → direct Supabase query with zero Gemini calls; a hackathon-only or project-only question → one agent + one Gemini call; a matching question → Project + Hackathon + Matcher agents, whose single batched Gemini call doubles as the final answer.

## Security / RLS summary

- **No public registration anywhere** — the login page has no sign-up path, and there is no INSERT policy on `profiles` for the `authenticated` role (only the service-role client, which bypasses RLS, can create one).
- **Enforced server-side, not just hidden in the UI.** Every table's RLS policy is the real gate — `projects`/`hackathons` require `is_admin()` for writes and `is_active_user()` for reads; submission/deletion requests require `submitted_by = auth.uid()` (or `is_admin()`) for visibility, and `is_admin()` for the update that approves/rejects.
- **No service-role key in the browser, ever** — it's a server-side environment variable used only inside `services/admin_service.py`.
- **No plaintext passwords anywhere** — Supabase Auth handles bcrypt hashing; this app's own tables have no password column.
- **Deactivation is immediate**, not just at next login, because RLS itself checks `is_active_user()`.

## Deployment

Runs unmodified with `streamlit run app.py`. Configuration is entirely environment-variable-driven — set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and (optionally) `SUPABASE_SERVICE_ROLE_KEY` as real environment variables or platform secrets, never commit `.env`.

Checklist:

- [ ] Migrations `0001`–`0013` all applied
- [ ] Initial admin bootstrapped via `scripts/bootstrap_admin.py`
- [ ] `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` set as real environment variables
- [ ] `.env` is not committed (already covered by `.gitignore`)
- [ ] No Gemini key set anywhere in deployment config — users provide their own
- [ ] pg_cron cleanup jobs confirmed scheduled (verify: `select * from cron.job;`)

## Known limitations

- Because the extension's project-insert RLS is now admin-only, non-admin users of the extension (if any) will see save failures — documented above as a deliberate consequence, not an oversight.
- `registration_link` is the hackathon dedup key "when possible" (per spec); a hackathon added with no link has no reliable duplicate protection.
- Manually entered hackathon times are treated as UTC; the form states this explicitly.
- The optional template-photo upload bucket (`0013`) is skippable — the form always accepts a plain image URL as a fallback.
