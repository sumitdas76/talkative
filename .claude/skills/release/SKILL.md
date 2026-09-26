---
name: release
description: Cut a new Talkative release (version bump, EXE rebuild, installer build, GitHub release). Use when publishing a new version of the app.
---

# Cutting a Talkative release

Since 2026-09-26 releases are built by GitHub Actions
(`.github/workflows/build.yml`), not on this machine -- builds from the
public source are what SignPath code signing requires.

1. **Bump the version in BOTH places** -- missed twice before (v1.1.1 and
   v1.1.2 shipped with the About tab on an old version). The workflow
   now fails if they disagree with each other or with the tag:
   - `installer\Talkative.iss` -- `MyAppVersion`
   - `talkative/__init__.py` -- `__version__`
   Never reuse a version number once its build differs from what shipped.
2. Add a `CHANGELOG.md` entry (plain language, user-facing).
3. Commit and push `main`.
4. Tag and push the tag: `git tag v<version>` then
   `git push origin v<version>`. The workflow builds the EXE, smoke-tests
   it, builds `TalkativeSetup.exe`, and attaches it plus `SHA256SUMS.txt`
   to a **draft** release. Watch it: `gh run watch <id> --exit-status`.
5. Check the draft: asset named exactly `TalkativeSetup.exe` (the in-app
   updater looks for that name), title/notes right. Replace the notes
   with the CHANGELOG entry.
6. Publish: `gh release edit v<version> --draft=false --latest`. Only
   then does the in-app updater offer it (drafts are invisible to
   `/releases/latest`).
7. Verify with `gh release list` that it's live and "Latest", and that
   `gh api repos/sumitdas76/talkative/releases/latest` shows a `sha256:`
   digest on the asset -- the updater refuses an update without one.
8. Optional: `.\scripts\rebuild.ps1` to bring this machine's local copies
   up to the new version (needs Talkative closed).

If `git push` or `gh release` get blocked by the permission classifier
even after the user confirmed, have the user run the command themselves
via `! <command>`. Run `gh` from PowerShell for large uploads (a past
upload from Git Bash/MinTTY failed with `Incorrect function`).
