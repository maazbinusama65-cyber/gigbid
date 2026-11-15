# Deploy on Render (free plan)

The repo ships a Render Blueprint (`render.yaml`) that builds `deploy/render/Dockerfile`: one container that starts the
GigSim stand-in marketplace and the API, and serves the web app from the same address.

## Steps
1. Sign in at render.com with GitHub and authorise the `maazbinusama65-cyber/gigbid` repository.
2. **New > Blueprint**, pick the repository, branch `main`, then **Apply**. Render reads `render.yaml`; nothing to configure.
3. Wait for the first build (about 5 to 10 minutes). Watch **Logs**: it ends with `serving on 0.0.0.0:10000`.
4. Open the service URL (`https://gigbid-xxxx.onrender.com`).
5. Sign in with the public demo account: **`reviewer@gigbid.demo` / `gigbid-demo`** (preloaded with the `ai_ml` persona).
6. Open a job in the inbox, analyse it, review the evidence, approve or edit the draft.

## What this deployment is
* The offline `stub` model profile on synthetic data: no API key and no running cost.
* No PyTorch, so retrieval uses the hashing embedder; search quality differs from the evaluated bge model.
* The free plan sleeps after 15 minutes idle and takes about a minute to wake: open the URL once before sharing it.
* Disk is ephemeral: runs and approvals reset when the service restarts.

## If it fails
* **Out of memory** in the logs: the free plan has 512 MB. Upgrade the service to a larger instance in Render, or use the
  Hugging Face route in `deploy/space/` (Docker Spaces need a paid plan).
* **Build error**: the build log names the failing step; paste it to whoever is helping.
* The Dockerfile was not built before it was committed.
