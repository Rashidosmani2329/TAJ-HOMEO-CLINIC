Build APK via GitHub Actions or WSL

Option A — GitHub Actions (no local Linux required):
1. Commit and push this repository to GitHub (branch `main`).
2. Go to the repository on GitHub → Actions → run the "Build Android APK" workflow or push to `main`.
3. When the workflow completes, download the artifact `apk-artifacts` from the workflow run.

Notes:
- The CI job runs `buildozer android debug` which will download the Android SDK/NDK and run the build; first run can take a long time.
- If the job fails due to missing system packages or licensing prompts, check Actions logs and install any missing apt packages locally in the workflow.

Option B — Build locally with WSL (recommended for iterative development):
1. Install WSL2 and an Ubuntu distribution on Windows.
2. Open WSL terminal and mount your project path, e.g. `cd /mnt/c/Users/RASHID/Music/Taj Homeo`
3. Make the helper script executable and run it:

```bash
chmod +x wsl_build.sh
./wsl_build.sh
```

Option C — Build using Docker (no local SDK/NDK installs beyond Docker):
1. Install Docker Desktop and ensure it's running.
2. From the project root run:

```bash
chmod +x docker_build.sh
./docker_build.sh
```

This script pulls the `kivy/buildozer` image, mounts your project and a persistent Buildozer cache (`~/.buildozer`), then runs `buildozer android debug` inside the container. The resulting APK (if successful) will be written to `./bin/` on your host filesystem.

APK location after success:
- `bin/` directory in project root (e.g. `bin/tajhomeo-0.1-debug.apk`) or the path shown by Buildozer in the logs.

OCR / pytesseract note:
- The original app used `pytesseract` which is a Python wrapper around the native Tesseract binary. The APK does NOT include the Tesseract binary. To add on-device OCR you must either:
  - Ship the Tesseract native binary for Android (complex; requires NDK and packaging), or
  - Use a remote OCR service (send images to a server for OCR), or
  - Use a pure-Python OCR alternative (limited accuracy).

If you want, I can attempt to integrate Tesseract into the APK (advanced).
