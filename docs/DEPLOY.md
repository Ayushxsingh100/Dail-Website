# Deploying DAIL Live on Vercel (free Hobby plan)

The site is the static folder `site/` and **one** Python function, `api/propose.py`, which asks Gemini with the authors' key. There is no build step and no dependency to install. Claude Code has not deployed this: the points marked **check** could not be tried.

## First deployment

1. **Vercel → Add New → Project → Import** `Ayushxsingh100/Dail-Website`.
2. **Configure Project:**
   - **Root Directory:** the repository root (leave it as `./`), **not** `site`. If the project was set up for the earlier version, change Root Directory from `site` back to `./` in Settings.
   - **Framework Preset:** `Other`.
   - **Build and install commands:** none. `vercel.json` sets them to nothing, serves `site/` as the static root (with one rewrite, so `/` serves `site/index.html`) and declares the one function `api/propose.py`.
3. **Environment variables** (Settings → Environment Variables):

   | Name | Needed | Value |
   |---|---|---|
   | `GEMINI_API_KEY` | yes | the Gemini key, marked **Sensitive** (in Vercel's newer screens the type is called Secret), environment **Production** only |
   | `DEMO_PASSCODE` | no | if set, visitors must type it before they can ask the AI; the page then shows a small passcode field. Mark it Sensitive |
   | `ALLOWED_ORIGINS` | no | comma-separated, for example `https://dail.example,https://www.dail.example`. Unset: only pages of the same host may ask |

   Type the key into Vercel yourself. Never put it in a file, a commit, a chat or a screenshot.
4. **Deploy.** An environment variable takes effect at the next deployment.

## Check after deploying

1. `https://<your site>/` opens the Ask screen (the rewrite), loads DAIL (about 17 MB), and the four pills read "SSH open to the internet" (red), "Database port closed", "Database not public", "App reaches database".
2. **check** `https://<your site>/api/propose` in the browser shows `{"available": true, "passcode_required": false, "model": "gemini-3.5-flash-lite"}` (`passcode_required` is `true` with a passcode). A 404 means Vercel did not pick up `api/`; a 500 means files are missing from the function.
3. **Ask →** gives a Gemini card and a DAIL card. **check** If it always fails, look at the function's bundle: it needs `dail_demo/`, `config/`, `site/vendor/dail/` and `site/vendor/scenarios/` (`includeFiles` and `excludeFiles` in `vercel.json`); brace globs in `includeFiles` and a writable temporary folder are not confirmed by Vercel's pages (D-34).
4. **check** `https://<your site>/dail_demo/proxy.py` and `/vercel.json` are 404: only `site/` is served.
5. In the browser's network panel, the answer of `/api/propose` holds `reply`, `model` and `tokens`, and nothing else.

## Keep it free

> - **The Google project behind the key must have no billing account.** Then it is on Gemini's free tier and cannot charge; the quota is the hard limit. Check it in Google AI Studio and in Google Cloud Billing.
> - **Vercel Hobby** does not bill for overage: "if you exceed your usage limits on the Hobby plan, you will have to wait until 30 days have passed before you can use the feature again" (Vercel's documentation, 26 Nov 2026). Do not add a payment method or upgrade.
> - **When the quota runs out,** visitors see "The AI's free quota is used up for now. Try again later, or write your own fix." Everything else keeps working.
> - The origin check keeps other *websites* from using the function. It does not stop a script that fakes the header, which could use up the day's free quota. Set `DEMO_PASSCODE` if that happens.
> - On the free tier, Google may use what visitors send to improve its products. The page says so.

## If the key is ever exposed

1. Google AI Studio → API keys: **delete** the key. This stops it at once.
2. Create a new key in a project without billing.
3. Replace `GEMINI_API_KEY` in Vercel and redeploy; on the laptop, `setx GEMINI_API_KEY "<new key>"` and a new terminal.
4. If it was ever committed, deleting it from the file is not enough: the old key must be deleted as in step 1.

## Local preview

```powershell
py -3.12 -m dail_demo serve          # http://127.0.0.1:8000/, with your local GEMINI_API_KEY
```

It runs the same proxy code as Vercel, on `127.0.0.1` only.

## Re-recording the replays, rebuilding the bundle

```powershell
py -3.12 -m dail_demo check
py -3.12 -m dail_demo record         # rewrites site/runs/
py -3.12 -m dail_demo bundle         # after a change to dail_demo/evaluate_core.py, browser.py or config/
py -3.12 -m unittest discover -s tests -p "test_*.py"
```

Commit on a branch and open a pull request; Vercel redeploys when it is merged.
