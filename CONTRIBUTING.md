# Contributing to Ovo

Thanks for helping. Ovo is a small project, so the bar is simple: keep it small, readable and reliable.

## Run it

```bash
git clone https://github.com/1iiron/ovo.git
cd ovo
pip install -r requirements.txt
python ovo.pyw
```

Windows 10 or 11 and Python 3.11 or newer.

## Check your change

```bash
python ovo.pyw --test
```

This runs the self-check at the bottom of `ovo.pyw`: plain `assert` lines for the logic (time formatting, settings, alerts, full-screen detection). If you add logic with a branch or a parser, add an assert for it there.

Then run Ovo and look at the window. A change to how things look needs a look at the real window, not just passing tests.

## Guidelines

- **One script.** The app is `ovo.pyw`. Please don't split it into packages without discussing it first.
- **Few dependencies.** The only runtime dependency is `pywebview`. Prefer the standard library.
- **Keep it quiet.** Ovo should never take focus, make sound, or draw attention except for the alerts you turned on.
- **Be careful with credentials.** Ovo reads the Codex login file and keeps a Claude login in `data/`. Never log, print or send those values.
- **Comments say why**, not what.

## Reporting a bug

Open an issue and include:

- your Windows version and how you run Ovo (the exe or from source),
- what you expected and what happened,
- a screenshot if it's about how it looks.

Don't paste anything from the `data/` folder or `~/.codex/auth.json`. They contain logins.

## Pull requests

- Keep each pull request to one change.
- Say what it does and how you checked it.
- Update the README if you change what users see.

By contributing you agree your work is released under the project's [MIT license](LICENSE).

## Releasing a new version (for maintainers)

Versions are three numbers: `1.1.0`. Ovo checks GitHub's latest release and offers the update to anyone running an older one.

1. Add a section to [CHANGELOG.md](CHANGELOG.md), newest first: `## 1.1.0 - 2026-12-01`, then the changes as a short list. That text becomes the release notes.
2. Make sure your work is committed and on `main`.
3. Run:

   ```bash
   python tools/release.py 1.1.0 --dry-run   # checks everything, changes nothing
   python tools/release.py 1.1.0             # bumps VERSION, rewrites the README, commits, tags v1.1.0 and pushes
   ```

   The script also rewrites the README's release text in that same commit: the release badge, the "Latest release" box (version, date, what's new, download link) and the download link in the install steps. They sit between the `<!-- latest-release:start -->` and `<!-- zip:start -->` markers, so leave those markers in place.

4. Pushing the tag starts the **Release** workflow (`.github/workflows/release.yml`). It checks the tag matches `VERSION`, runs the self-test, builds `Ovo.exe`, writes the checksum and publishes the release with the zip and `.sha256` file attached. Watch it in the repository's **Actions** tab.

Never edit or re-upload files on a published release: the checksum Ovo checks is the one published with it. If a release is wrong, publish a new, higher version.
