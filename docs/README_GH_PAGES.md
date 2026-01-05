Publish `docs/` to GitHub Pages (recommended quick hosting)

1. Create a GitHub repository and push this project (if not already).
2. Ensure `docs/update.json` exists (we created it).
3. In the repo settings, enable GitHub Pages and set the source to `docs/` branch or `main` branch `docs` folder.
4. Wait a minute; your metadata will be available at:
   https://<your-github-username>.github.io/<repo>/update.json

Steps to host the EXE (choose one):
- Option A (GitHub Releases):
  1. Create a Release and attach `dist/TajHomeoApp.exe` to it.
  2. Use the release `download` URL as the `url` field in `docs/update.json`.
- Option B (Pages):
  1. Commit `dist/TajHomeoApp.exe` into `docs/` (warning: large binary in git).
  2. Pages will serve it at: https://<user>.github.io/<repo>/TajHomeoApp.exe

After hosting:
- Edit `homeo_patient_app.py` and set `UPDATE_METADATA_URL` to the Pages URL above.
- Rebuild the app or run from source; users can click `Check Updates` (toolbar 'Upd') to fetch and install.

Security note:
- Prefer Releases or a proper static file host (S3 + CloudFront) for large binaries.
- Keep `update.json` served over HTTPS.
