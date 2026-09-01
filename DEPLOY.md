# Deploying the melanoma explanation survey

The deployed app serves explanations from `precomputed/` and never loads torch.
That is what makes free hosting possible: live inference peaks at **1.67 GB RAM**
and ~15 s per Phase 4 question, against a free tier's ~1 GB and a participant's
patience. Serving from cache uses ~300 MB and answers in ~1 ms.

---

## Step 1 — Google Sheet for responses (do this first)

**A hosted app has an ephemeral filesystem: `data/*.csv` is wiped on every
restart and redeploy. Google Sheets is the only durable store. If you skip this
step you will lose every response.**

1. Create a Google Sheet named exactly **`Melanoma_Survey_Results`**.
2. Go to <https://console.cloud.google.com/> → create a project.
3. Enable **Google Sheets API** and **Google Drive API**.
4. **Credentials → Create credentials → Service account**. Any name.
5. Open the service account → **Keys → Add key → JSON**. A file downloads.
6. Open that JSON, copy the `client_email` value (ends `...iam.gserviceaccount.com`).
7. Back in your Sheet: **Share** → paste that email → **Editor** → Send.

Tabs (`participants`, `phase1_responses`, …) are created automatically on first write.

## Step 2 — Build the deployable copy

```bash
python precompute.py      # ~3 min, only needed if the cache is missing or stale
python build_deploy.py    # writes ../survey_deploy and git-commits it
```

`build_deploy.py` copies only what the survey runs on. It leaves behind `vendor/`
(4.6 GB), `datasets/` (254 MB) and the training checkpoints, and starts a fresh
git history so none of that bulk is ever committed.

## Step 3 — Push to GitHub

Create an **empty** repo at <https://github.com/new> — no README, no .gitignore.
It can be public or private; Streamlit Cloud handles both. Then:

```bash
cd ../survey_deploy
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```

The push is a few hundred MB and takes a couple of minutes.

## Step 4 — Deploy on Streamlit Community Cloud

1. Sign in at <https://share.streamlit.io> with the same GitHub account.
2. **Create app** → **Deploy a public app from GitHub**.
3. Repository: your repo. Branch: `main`. Main file path: `Home.py`.
4. Before clicking Deploy, open **Advanced settings → Secrets** and paste the
   contents of your service-account JSON in this shape:

   ```toml
   [gcp_service_account]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\nMII...\n-----END PRIVATE KEY-----\n"
   client_email = "...@....iam.gserviceaccount.com"
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."
   ```

   Copy `private_key` **exactly** as it appears in the JSON, keeping the literal
   `\n` sequences and the surrounding quotes. This is the single most common
   cause of a failed deploy.
5. **Deploy.** First build takes 2–5 minutes.

You get a URL like `https://<your-app>.streamlit.app` — that is the link to send
to participants.

## Step 5 — Verify before recruiting anyone

- [ ] Register on the intro page, then confirm the row appears in the
      `participants` tab of your Sheet.
- [ ] Answer one Phase 1 question; check the `phase1_responses` tab.
- [ ] Open a Phase 4 question and all four explanation types. They should appear
      instantly. A red "Could not save your response" banner means the Sheets
      credentials are wrong — fix before continuing.
- [ ] Reboot the app from the Streamlit dashboard, then confirm your earlier rows
      are still in the Sheet. This is the test that proves nothing will be lost.

---

## Notes

**Sleeping.** A free app sleeps after ~7 days with no visitors and wakes on the
next visit, taking ~30 s. Harmless for an active survey; visit the link weekly
during a long recruitment period.

**Changing the Phase 4 image set.** `PHASE4_SAMPLE_SEED` and
`PHASE4_IMAGES_PER_LABEL` in `phase4_pages.py` determine which images are used.
Change either, then rerun `precompute.py` and `build_deploy.py` — otherwise
participants hit images with no cached explanation.

**Running live models locally.** Set `SURVEY_LIVE_INFERENCE=1` and install
`requirements-dev.txt`. The cache is bypassed and the real models run.

**Regenerating the cache.** `python precompute.py --force`, or
`--kinds prototree` for one backend. Reruns are safe: finished work is skipped
and stale artifacts are cleared.

**Language.** The survey runs in Vietnamese. It sits in three places:

- *Page copy* — written directly into `Home.py`, `intro_page.py`,
  `phase{1,2,3,4}_pages.py` and `thank_you_page.py`.
- *Values that come out of the model cache* (`Benign`/`Melanoma`, the 7-point
  checklist attributes and states, the clustering note) — translated for display
  only, by `i18n.py`. **What is saved stays English**: the diagnosis written to
  Sheets, the `checklist_table` in `precomputed/manifest.json` and every CSV
  column name are unchanged, so `fetch_responses.py`, `reconcile_phase4.py` and
  `dedupe_responses.py` keep working and results stay comparable with the
  English-language run.
- *Text drawn inside the explanation figures and PDFs* — hardcoded in the model
  code under `vendor/` (`heatmap_explain/resnet_model.py`,
  `clustering/cluster.py`, `ProtoTree/util/visualize*.py`,
  `weakly_supervised_prototype/src/infer.py`) and in the weakly supervised PDF
  built by `utils.py`. Changing any of these needs `precompute.py --force`
  afterwards; the wording is baked into the cached artifacts.

Two font details make the diacritics render. reportlab's built-in Helvetica is
Latin-1, so `pdf_fonts.install()` re-registers a Unicode face under that name
before any PDF is drawn — `precompute.py` and `utils.py` both call it. Graphviz
draws the ProtoTree diagrams instead, so those `.dot` files are written as UTF-8
and ask for Arial rather than Helvetica.

Page 1 of every ProtoTree PDF is the static
`runs/prototree_ph2_depth3/pruned_and_projected/treevis.pdf`, produced at
training time and merged in front of the per-image page. It is not rebuilt by
inference: to relabel it, edit `treevis.dot` beside it and re-render with
`dot -Tpdf -Gmargin=0 <dot> -o <pdf>` from the `vendor/ProtoTree` directory. The
English originals are kept next to it as `treevis.dot.en.bak` / `treevis.pdf.en.bak`.

---

## Getting responses back into `data/`

The deployed app writes to Google Sheets, because anything it writes to disk is
erased on the next restart. To pull that data down into the usual local layout:

```bash
python fetch_responses.py
```

This writes `data/participants.csv`, `data/phase1_responses.csv`,
`data/phase2_responses.csv`, `data/phase3_responses.csv`,
`data/phase4_responses_flat.csv`, `data/comments.csv`, and rebuilds the nested
`data/phase4_responses.json` from the flat Phase 4 scores.

It needs the same credentials as the app. For local use, either put
`service_account.json` beside `utils.py`, or create `.streamlit/secrets.toml`
with the `[gcp_service_account]` block from Step 4. **Neither file is committed** —
both are in `.gitignore`.

`fetch_responses.py` **overwrites** the local CSVs with what is in Sheets. If you
have local rows collected before Sheets was connected, use:

```bash
python fetch_responses.py --merge
```

which takes the union, de-duplicated on `Timestamp` + `Name` + `Email`.

Run it whenever you want a local snapshot; Sheets remains the source of truth.
