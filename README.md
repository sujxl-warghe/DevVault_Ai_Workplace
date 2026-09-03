# DevVault

**Save inspiration. Find the perfect fit.**

A Chrome Extension for [Devpost](https://devpost.com) that lets you:

1. Bookmark projects straight from a hackathon's **Project Gallery** with a single click — no need to open each project page.
2. Automatically detect and track hackathons you've actually **joined/registered for**, with expired hackathons cleaned up server-side.
3. Export everything you've saved to **Excel** or **CSV**.

This repo builds the Chrome Extension, its Supabase database, and export tooling only. The future AI recommendation chatbot (which will read from the same `projects` and `joined_hackathons` tables) is a separate project.

> **Phase 2:** the AI workspace now exists at [`streamlit_app/`](./streamlit_app/) — a separate Streamlit application that reads the same Supabase database. See `streamlit_app/README.md` for setup. It does not modify or duplicate anything in this extension.

> **Phase 3:** the Streamlit app is now deployment-ready — manual project/hackathon entry, a new global (shared, not per-user) `hackathons` catalog with its own migrations (`supabase/migrations/0005`–`0007`), a deterministic matching engine, robust Gemini retry/fallback handling, and per-user Gemini API keys entered in-app. See `streamlit_app/README.md` for the full picture. This extension was not touched.

> **Phase 4:** the Streamlit app is now multi-user with admin-moderated content. No public registration — a single bootstrapped admin (`scripts/bootstrap_admin.py`) creates every account; usernames map to synthetic Supabase Auth emails under the hood. Projects and hackathons are minimal (Title/Details/Repo Link/Live Link, and Name/Template-Photo/Start/End/Registration-Link/Prize-Pool) and fully global, but normal users can only submit add/delete requests for an admin to approve or reject (`supabase/migrations/0008`–`0013`). Full details in `streamlit_app/README.md`. This extension was, again, not touched.

---

## 1. What DevVault does

- **On a Devpost Project Gallery page:** every project card gets a `+ Add to DevVault` button. Clicking it (and only clicking it — nothing is auto-saved) extracts the project's title, tagline/thumbnail from the card, fetches the project's own Devpost page in the background to fill in the description, "what problem it solves," tags, GitHub link, and demo link, then saves it to Supabase. The button becomes `✓ Saved`. Already-saved projects are marked `✓ Saved` automatically when you revisit a gallery (checked in one batched query, not one request per card). New cards loaded via infinite scroll get buttons automatically.
- **On any Devpost page:** DevVault looks for concrete evidence that you've joined/registered for that hackathon (an "unregister" control, a participant banner, explicit "you've joined" style copy, etc.) — never just for having visited the page. When found, it upserts the hackathon (keyed by its Devpost URL) into `joined_hackathons`, including its submission deadline and prize pool (total amount plus a per-tier breakdown, when Devpost's Prizes section is present).
- **Expired hackathons are deleted automatically**, server-side, by a Supabase `pg_cron` job — independent of whether the browser or extension is even open.
- **The popup dashboard** has two tabs: Saved Projects (search, view, delete, open GitHub/Demo/Devpost) and Joined Hackathons (active only, soonest deadline first).
- **Export to Excel/CSV** produces `DevVault_Projects_YYYY-MM-DD.xlsx` / `.csv` with Title, What Problem It Solves, GitHub, Demo Link, and Devpost Link — URLs as clickable hyperlinks in the Excel file.

## 2. Architecture

```
src/
  background/            Service worker — owns the Supabase client & auth session,
                          routes messages from content scripts (save/check/sync/auth)
  content/
    project-gallery/      Injects "+ Add to DevVault" buttons, MutationObserver for
                          infinite scroll, per-card extraction + enrichment fetch
    hackathons/            Detects joined-hackathon evidence, extracts deadline, syncs
  popup/                 React + Tailwind dashboard (Saved Projects / Joined Hackathons)
  services/
    supabase/              Supabase client (chrome.storage-backed session), auth helpers
    projects/              Save / batch-check / list / delete / update / search
    hackathons/             Upsert-sync / list-active
    export/                 Excel (SheetJS) and CSV export
  utils/
    devpost/               DOM extraction (gallery cards, project pages, hackathon pages)
    dates/                 Reliable ISO date parsing, "time remaining" formatting
    urls/                  GitHub/demo/devpost URL classification heuristics
  types/                  Shared TypeScript types (mirrors the DB schema)
  constants/              Centralized, multi-fallback CSS selectors + config
supabase/migrations/      SQL: schema, RLS policies, scheduled cleanup
```

**Design principles carried through the code:**
- DOM extraction, database access, UI, and export logic are kept in separate modules.
- Every Devpost selector has fallbacks (see `src/constants/selectors.ts`) and extraction never throws — missing fields become `null`/`[]`, never invented data.
- A project is saved **only** on an explicit button click. A hackathon is saved **only** when there's reliable evidence of joining, never just from visiting its page.
- `devpost_url` is the single source of truth for de-duplication in both tables (`UNIQUE` + `ON CONFLICT` upsert), so races and duplicate detections can't create duplicate rows.

## 3. Requirements

- Node.js 18+ and npm
- A free [Supabase](https://supabase.com) project
- Google Chrome (or any Chromium browser that supports Manifest V3)

## 4. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) → **New project**.
2. Note your **Project URL** and **anon public key** (Project Settings → API). You'll need these for `.env`.

## 5. Run the SQL migrations

In the Supabase Dashboard, open **SQL Editor** and run these files **in order** (or use the Supabase CLI: `supabase db push` against `supabase/migrations/`):

1. `supabase/migrations/0001_init_schema.sql` — creates `projects` and `joined_hackathons`, indexes, `updated_at` triggers.
2. `supabase/migrations/0002_row_level_security.sql` — enables RLS and per-user policies.
3. `supabase/migrations/0003_scheduled_cleanup.sql` — enables `pg_cron` and schedules hourly deletion of expired hackathons.
4. `supabase/migrations/0004_add_prizes.sql` — adds `prize_amount` and `prizes` columns to `joined_hackathons` for the prize-pool feature.

## 6. Configure RLS

Migration `0002` already sets this up: every table requires an authenticated session, and each policy restricts rows to `auth.uid() = user_id`. You don't need to do anything else in the dashboard — just make sure step 5's migrations ran without error. If `pg_cron` fails to enable in step 5's migration 3, enable it manually first: **Database → Extensions → search "pg_cron" → Enable**, then re-run that migration (or create the equivalent job from **Database → Cron Jobs** in the dashboard UI).

## 7. Configure scheduled expired-hackathon cleanup

Handled by `0003_scheduled_cleanup.sql`. It creates a `cleanup_expired_hackathons()` function and schedules it hourly via `pg_cron`. To verify it's running:

```sql
select * from cron.job where jobname = 'devvault-cleanup-expired-hackathons';
select * from cron.job_run_details order by start_time desc limit 5;
```

You can also run `select public.cleanup_expired_hackathons();` manually at any time.

## 8. Create the `.env` file

```bash
cp .env.example .env
```

Fill in:

```
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-public-key
```

Never put your `service_role` key here or anywhere else in this project — see **Security considerations** below.

## 9. Install dependencies

```bash
npm install
```

## 10. Build the extension

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm run build        # tsc --noEmit && vite build → outputs to dist/
```

`dist/` is a complete, loadable Chrome extension.

## 11. Load it as an unpacked Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `dist/` folder produced by `npm run build`
5. Pin the DevVault icon, click it, and sign up / sign in (Supabase email+password — see **Authentication** below)

Whenever you change `.env` or source files, re-run `npm run build` and click the refresh icon on the extension card in `chrome://extensions`.

## 12. Test Devpost Project Gallery buttons

1. Sign in via the popup first (saves require an authenticated session).
2. Visit any hackathon's project gallery on Devpost (e.g. `https://<hackathon>.devpost.com/project-gallery`).
3. Each project card should show a `+ Add to DevVault` button.
4. Click one: it shows `Saving...`, fetches the project's own page in the background (you stay on the gallery), then becomes `✓ Saved`.
5. Scroll to trigger more cards loading (if the gallery paginates via infinite scroll) — new cards should get buttons automatically, without duplicating buttons on existing ones.
6. Reload the gallery — previously saved projects should immediately show `✓ Saved` (one batched Supabase check, not one per card).

## 13. How joined hackathon detection works

DevVault only stores a hackathon when the page shows explicit, conservative evidence you've joined it — an "unregister" control, a participant banner, or specific confirmatory phrasing (see `JOINED_EVIDENCE_SELECTORS` / `JOINED_EVIDENCE_PHRASES` in `src/constants/selectors.ts`). Simply browsing a hackathon's page never saves it. When evidence is found, the hackathon's name, description, start/end dates (parsed only from machine-readable `<time datetime>` / `data-*` attributes — never guessed from human-readable labels) are upserted keyed by the hackathon's Devpost URL, so revisiting it just refreshes the record instead of duplicating it. If a deadline can't be reliably parsed, DevVault logs it and skips saving rather than storing a fake date.

## 14. How Excel/CSV export works

The popup's **Saved Projects** tab has **Export to Excel** and **Export to CSV** buttons. Both read all saved projects from Supabase and generate the file entirely client-side (via SheetJS for `.xlsx`) before triggering a browser download — GitHub/Demo/Devpost columns are real clickable hyperlinks in the Excel file. Filenames: `DevVault_Projects_YYYY-MM-DD.xlsx` / `.csv`.

## 15. Security considerations

- The extension bundle only ever contains `VITE_SUPABASE_ANON_KEY` — the `service_role` key must never be placed in `.env`, source, or committed to git (`.gitignore` excludes `.env*`).
- Row Level Security is mandatory here: without it, the shipped anon key alone would let anyone read/write all rows. Migration `0002` enables RLS and scopes every policy to `auth.uid() = user_id`.
- Authentication is Supabase email/password, chosen because magic links require a redirect landing page that's awkward inside an extension popup; the session is persisted via a `chrome.storage.local`-backed adapter (see `src/services/supabase/chromeStorageAdapter.ts`) so it survives service worker restarts.
- The extension requests only `storage` and `downloads` permissions, plus host permissions scoped to `devpost.com`/`*.devpost.com` — not `<all_urls>`.
- The `devpost_url` fetch for enrichment happens from the content script (same-origin as the page you're on), not from a privileged context with broader access.

## 16. Known limitations

- Devpost's DOM can change; extraction uses multiple fallback selectors and semantic heuristics, but a large enough Devpost redesign may still require updating `src/constants/selectors.ts`.
- Demo-link detection is heuristic (excludes Devpost/GitHub/social links, prefers common app-hosting domains); with multiple ambiguous external links it may correctly leave `demo_url` empty rather than guess wrong.
- Joined-hackathon detection depends on Devpost's UI exposing some explicit "you've joined" signal on the page; hackathons with unusual custom templates may not be detected.
- `pg_cron`'s scheduling granularity here is hourly; an expired hackathon may remain in the "active" list for up to ~59 minutes after its deadline from the cron job's perspective alone — but the `end_at > NOW()` filter used everywhere in the extension's own queries means it will never be *displayed* as active past its deadline, regardless of cron timing.
- This is designed for personal, single-account use per browser profile; the schema already carries `user_id` so it can extend to multi-user later without migration surgery.
