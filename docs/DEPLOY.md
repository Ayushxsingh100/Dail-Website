# Deploying DAIL Live on Vercel (free Hobby plan)

The website is the folder `site/`: static files only (HTML, CSS, JavaScript, JSON, the bundled DAIL source and the self-hosted Pyodide runtime). It has no build step, no server code, no serverless function, no environment variable and no secret. Nothing in `site/` calls Gemini.

## First deployment

1. Sign in at https://vercel.com with the GitHub account that owns `Ayushxsingh100/Dail-Website` (the Hobby plan is free).
2. **Add New → Project**, then **Import** the repository `Ayushxsingh100/Dail-Website`.
3. In **Configure Project**:
   - **Framework Preset:** `Other`
   - **Root Directory:** `site`
   - **Build Command:** leave empty (override it to empty if Vercel fills one in)
   - **Output Directory:** `.`
   - **Install Command:** leave empty
   - **Environment Variables:** none. Never add `GEMINI_API_KEY` or any other key to Vercel.
4. Press **Deploy**. Vercel serves `site/index.html` at the project's address.
5. Open the address and check:
   - **Replays** shows the canonical regression REJECT;
   - **Live** loads "Loading DAIL into your browser (~16.8 MB)", then **Fill: the repair that breaks INV-FUNC-001** and **Submit to the gate** gives REJECT with target-only PROMOTE;
   - `credits.html` opens.

Every push to `main` redeploys automatically. Pull requests get preview deployments.

## Re-recording the replays and redeploying

The replays in `site/runs/` are recorded on the authors' laptop, never on Vercel.

```powershell
# a new terminal, with DAIL_ROOT, TERRAPRESERVE_ROOT, DAIL_LIVE_DATA, DAIL_TERRAFORM_MIRROR
# (and, for the Gemini runs, GEMINI_API_KEY) set as in the README
py -3.12 -m dail_demo check
py -3.12 -m dail_demo record      # rewrites site/runs/ and site/runs/index.json
py -3.12 -m unittest discover -s tests -p "test_*.py"
```

`record` refuses to write any trace that contains the key or a local path. Commit `site/runs/` on a branch, open a pull request, and merge it after review; Vercel then redeploys.

If DAIL Live's own Python files change (`dail_demo/evaluate_core.py`, `dail_demo/browser.py`, the reviewed `config/*.toml`) or the curated scenarios change, rebuild the bundle before committing:

```powershell
py -3.12 -m dail_demo bundle      # rewrites site/vendor/ except Pyodide, whose pinned hashes it checks
```

`tests/test_bundle.py` fails if the committed `site/vendor/` differs from a fresh bundle.

## Local preview

```powershell
py -3.12 -m http.server --bind 127.0.0.1 -d site 8000
```

Then open http://127.0.0.1:8000/. Live mode needs `127.0.0.1` or https (the browser checks each bundled file's SHA-256 with the Web Crypto API).
