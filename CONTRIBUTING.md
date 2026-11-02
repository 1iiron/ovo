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
