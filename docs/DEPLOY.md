# Deploy PropCloser (free tier, ~30 minutes)

Order matters: **database → API → website → keep-alive**. Never put keys in code; use each platform's secrets.

## 1. Neon Postgres (long-term memory + data)

1. Sign up at neon.tech → **New project**. Pick the region **closest to the API, not to you**: every turn makes several
   database round trips, and across oceans each one costs about 0.25 s. Hugging Face Spaces run in the US, so choose
   **AWS US East (N. Virginia)**. On Render, pick the same region on both sides.
2. **Connection details** → untick *Connection pooling* → copy the **direct** connection string
   (`postgresql://…neon.tech/neondb?sslmode=require`).
3. That's it — the API creates every table and seeds the 30 listings on first start.

> Why direct, not pooled? LangGraph's Postgres checkpointer uses pipelined queries that PgBouncer's
> transaction mode can break. The direct URL avoids that.

## 2. Agent API on Hugging Face Spaces (Docker)

1. huggingface.co → **New Space** → name `propcloser-api` → SDK **Docker** → *Blank* → **Public** → Create.
2. Space **Settings → Variables and secrets** → add **secrets**:
   - `ANTHROPIC_API_KEY` — your group key
   - `DATABASE_URL` — the Neon direct URL
   - `ADMIN_TOKEN` — random, 12+ characters (the dashboard password). Weak or missing = the admin API stays closed
3. Push the `backend/` folder to the Space (from the repo root):

   ```bash
   git remote add space https://huggingface.co/spaces/<hf-username>/propcloser-api
   git subtree push --prefix backend space main
   ```
   When asked for a password, use a Hugging Face **access token** with write permission
   (Settings → Access Tokens).
4. Wait for the build (Logs tab). Check `/health` → `ok`, then **`/ready`** → `{"ready": true, "storage": "postgres"}`.
   If `ready` is false, `problems` says exactly what is missing (key, database, spend cap).
5. Smoke test:

   ```bash
   curl -X POST https://<hf-username>-propcloser-api.hf.space/chat \
     -H "Content-Type: application/json" \
     -d '{"user_id":"demo","thread_id":"1","message":"3 bed house in Bahria Town under 3 crore"}'
   ```

To redeploy after changes: commit, then run the `git subtree push` command again.

**Alternative — Render:** New → Blueprint → pick this repo (uses `render.yaml`) → fill the three secrets.
Render's free tier sleeps after ~15 minutes, so turn on the keep-alive below.

## 3. Website on Vercel

1. Edit `frontend/config.js` → set `window.PROPCLOSER_API` to your Space URL. Commit and push.
2. vercel.com → **Add New → Project** → import this GitHub repo.
3. **Root Directory:** `frontend` · **Framework preset:** Other · no build command → **Deploy**.
4. Open the site, try the chat, then open `/admin` and sign in with your `ADMIN_TOKEN`.
5. Optional: set `ALLOWED_ORIGINS` on the Space to your Vercel URL to lock down browser access
   (the graded `/chat` endpoint stays open for the grader either way — it isn't a browser).

## 4. Keep it alive until Wednesday

GitHub repo → **Settings → Secrets and variables → Actions → Variables** → add `API_URL` =
your Space URL. The `keep-alive` workflow then pings `/health` and `/ready` every 10 minutes (keeps Neon awake too).
Run it once by hand from the **Actions** tab to check it works.

## 5. Before submitting

```bash
cd backend
python tests/run_bench.py --url https://<hf-username>-propcloser-api.hf.space
```
Paste the table from `benchmark_results.md` into the README's **Benchmark** section.

Before the first deploy run `python check_model.py` locally: it proves the key, the tools and the **prompt cache** work.

Cost check: `GET /admin/usage` shows dollars spent, cache hit rate and the caps. Details: `docs/COSTS.md`.
