# Setup

What you need to do on GitHub to get the tracker running. It takes about ten minutes.

The repository is `rethinksci-gif/plastics-policy-tracker` and the site is served at
<https://rethinksci-gif.github.io/plastics-policy-tracker/>.

## 1. Create the repository (skip if it already exists)

From a terminal on the machine that holds the code:

```bash
cd ~/projects/plastics-policy-tracker
gh repo create rethinksci-gif/plastics-policy-tracker --public --source . --remote origin --push \
  --description "Plastics laws and regulations worldwide, tracked and checked against official sources"
```

## 2. Add the DeepSeek API key (the only secret)

1. Open the repository on GitHub → **Settings** → **Secrets and variables** → **Actions**.
2. On the **Secrets** tab, click **New repository secret**.
3. Name: `DEEPSEEK_API_KEY`. Secret: your key from <https://platform.deepseek.com/api_keys>.
4. Click **Add secret**.

Optional, on the **Variables** tab of the same page (no secret needed; defaults in brackets):

| Variable | Purpose |
|---|---|
| `DEEPSEEK_MODEL_FAST` | Model for triage (`deepseek-flash`) |
| `DEEPSEEK_MODEL_PRO` | Model for drafting and review (`deepseek-v4-pro`) |
| `MAX_LLM_CALLS_PER_RUN` | Cost cap per run (`300`); the run stops and opens an issue when reached |

## 3. Turn on GitHub Pages

1. **Settings** → **Pages**.
2. Under **Build and deployment** → **Source**, choose **GitHub Actions**. You don't need to pick a branch.
3. Go to **Actions** → **Deploy site** → **Run workflow** (branch `main`) to publish the first version.
   The URL appears in the run summary and on the Pages settings page.

## 4. Allow the workflows to write

1. **Settings** → **Actions** → **General**.
2. Under **Workflow permissions**, select **Read and write permissions** and tick
   **Allow GitHub Actions to create and approve pull requests**. Click **Save**.

The workflows need this to commit to the `staging` branch, open the staging PR and open `needs-human-review` issues.

## 5. Test both workflows by hand

1. **Actions** → **Daily pipeline** → **Run workflow**. Tick **dry_run** for a first test: it fetches, triages,
   drafts and reviews, uploads everything as an artefact, and changes nothing. Then run it again without
   dry_run: it commits to `staging` and opens the staging PR.
2. **Actions** → **Biweekly issue** → **Run workflow**. **dry_run** is ticked by default: it composes the draft
   issue and the review report as an artefact. Untick it to publish an issue now.

## How it runs afterwards

| Workflow | When | What |
|---|---|---|
| Daily pipeline | Every day 05:15 UTC | fetch → triage → draft → review (layers 1–3); commits to `staging`; opens issues for quarantined items |
| Biweekly issue | Mondays 06:00 UTC; publishes on even weeks counted from ISO week 42 of 2026 | layer 1–2 re-check, layer 4 editorial review, publish gate; merges `staging` into `main` and deploys |
| Deploy site | Every push to `main`, and when called by the biweekly workflow | Astro build + Pagefind → GitHub Pages |
| CI | Pull requests and pushes | Unit tests, layer 1–2 check of every dossier, site build |

To change the publishing weeks, edit `schedule.anchor_iso_year` / `anchor_iso_week` in `config.yaml`.

## When the publish gate closes

If more than 30% of an issue's items are quarantined, or any high-impact item is quarantined, the issue is not
published. You get a PR from `staging` that @-mentions you, with the reasons and a link to the draft.

- To publish after checking: **Actions** → **Biweekly issue** → **Run workflow**, untick **dry_run**, tick
  **force_publish**. (Merging the PR alone does not publish the issue: the dossier updates are applied by the workflow.)
- To fix a quarantined item: edit `data/candidates/<id>.json`, set `"status": "drafted"` and run the daily
  workflow. It goes through all review layers again.
- To drop it: close its `needs-human-review` issue and set its status to `"discarded"`.

## Local use

```bash
uv sync
export DEEPSEEK_API_KEY=...            # never commit it
uv run pytest -q                        # review gates
uv run python -m pipeline validate      # layer 1+2 over every dossier
uv run python -m pipeline daily --dry-run
uv run python -m pipeline biweekly --force --dry-run
cd site && npm ci && SHOW_DRAFTS=1 npm run build && npm run preview
```

## Not set up yet (optional)

- **Custom domain:** not used. To add one later, put the domain in `site/public/CNAME`, set `site`/`base` in
  `site/astro.config.mjs` and `config.yaml`, and add the DNS records GitHub shows under Settings → Pages.
- **Légifrance:** register a PISTE API client to follow the French Journal officiel (see `sources/unreachable.md`).
- **WTO ePing:** subscribe to e-mail alerts (see the `wto-eping` entry in `sources/feeds.yaml`).
