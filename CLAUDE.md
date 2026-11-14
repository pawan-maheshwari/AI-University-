# AI University — Claude working guide

Static site on GitHub Pages → **ai-university.co.in** (CNAME). A catalogue of
interactive AI courses, labs, simulators and executive tools, with Supabase login,
certificates and Open Badges. No build step: committed files are served as-is.
Owner: Pawan Maheshwari (planetAI LLP).

## Token rules (read first)
- Huge files: `thinking-shelf.html` 3.2 MB, `index.html` 2.1 MB / 9.6k lines / 84 base64
  lines, `seven-lanterns.html` 0.9 MB, `index_university.html` 1.1 MB. Never `Read` these
  whole; never print their lines unclipped. Use `tools/claude/peek.sh` (clips lines).
- Find code via `docs/CODEMAP.md` (line-numbered anchors per file). Grep the map.
- Ignore snapshots `index_bac*.html`, `index_040726/050726.html` (blocked in
  `.claude/settings.json`). `vendor/supabase.js` is a vendored lib — never read it.
- Each course/tool is its own self-contained HTML file. **A new feature is almost always a
  new file + one registry entry** — you rarely need to open other pages.

## Architecture
- `index.html` = home + catalogue. Inline JS registries drive the cards (grep with
  `peek.sh index.html -f NAME`): `COURSES`, `EXCLUSIVE`, `EXCLUSIVE_READING`, `TOOLS`,
  `PAPERS`, `POLICY`, `TEAM`, `ZONES`, `IMG`. Entry shape:
  `{id, img, file:"x.html", label, meta|age, tag, points:[…]}`. Card art lives in `IMG`
  (inline SVG/base64 — don't print it) or `img/*.svg`.
- Auth: `login.html` + `login.js`, `account.html` + `account.js`, shared
  `aiu-auth.js` / `aiu-auth.css` (Supabase via `vendor/supabase.js`, Cloudflare Turnstile).
  DB: `schema.sql`, `01 certificates.sql`, `mfa-policies.sql`. Edge functions in
  `supabase/functions/` (`badge-assertion`, `create-order`, `issue-certificate`).
- Credentials: `openbadges/*.json` (one badge class per programme, art in `img/`).
- `labs/*.ipynb` — Python notebooks (open with `jq '.cells[].source'`, not whole).
- `kidswear-poc/` — Python retail pipeline (numbered steps `01_…18_`, `run_all.sh`,
  tests in `tests/`) that generates `kidswear-planner.html`. See its README. Results are
  regenerated, never hand-edited. Workflow `kidswear-retrain.yml`.
- `ai-library.html` also exists (diverged) in the ai-shorts repo — ask before syncing them.
- SEO: update `sitemap.xml` when adding a public page.

## Recipes
- **New course / tool / lab page** → copy the closest existing page's skeleton (read only its
  `<head>` + first section with `peek.sh`), build `new-thing.html` as one self-contained file
  (inline CSS/JS, no new CDNs), add one entry to the right registry in `index.html`, add
  to `sitemap.xml`. Courses must be interactive with visuals, not text-only.
- **Gate a page behind login** → include `aiu-auth.css` + `aiu-auth.js` the way
  `account.html` does (grep `aiu-auth` there).
- **Verify** → `python3 tools/claude/check_html.py <file>` (parses every inline script).
- After adding/renaming files or sections → `python3 tools/claude/codemap.py`.

Slash commands: `/feature <ask>`, `/fix <symptom>`.
