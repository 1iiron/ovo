# Security

Ovo handles logins: it keeps a claude.ai session in its data folder and reads the Codex login file. If you find a way that could leak or misuse them, please tell me privately first.

**Don't open a public issue for a security problem.** Use this repository's **Security** tab → **Report a vulnerability** (GitHub's private reporting).

Please include what you found, how to reproduce it, and what it could let someone do. I'll reply as soon as I can and fix it before sharing details.

## What Ovo does, and doesn't do

- **No server.** Ovo opens no listening port, TCP or UDP, and nothing on your PC or network can connect to it. The packaged and source versions were both checked with the Windows socket list while running.
- **Three destinations only.** It makes outgoing HTTPS requests to `claude.ai` and `chatgpt.com` (your usage) and to GitHub's own hosts (the update check). No telemetry, no analytics. The update check can be turned off in Settings.
- **Updates are checked, and always ask first.** The check sends nothing about you: it is a plain request for this project's latest release. Only the release's version and file names are read from the reply. The download addresses are built by Ovo from the checked version, never taken from the reply, and only `https` addresses on GitHub's hosts are allowed, redirects included. The new `Ovo.exe` is installed only if the zip's SHA-256 matches the checksum file published with the release, the zip holds a plain `Ovo.exe`, and you pressed **Update**. If anything is off, the running copy is left alone. The exe isn't code-signed, so this guards against a damaged or swapped download, not against someone who controls the publishing GitHub account.
- **Your Codex login is read, never copied.** Ovo reads `~/.codex/auth.json` and never writes to it. The token is sent only to `https://chatgpt.com/backend-api/wham/usage`. That request never follows a redirect, so a redirect cannot carry the token to another site. The token is never printed, logged or stored anywhere else.
- **Your Claude login stays in the browser profile.** It lives in Ovo's data folder (`data/` next to the script, or `%APPDATA%\Ovo` for the packaged app), where only your Windows account can read it.
- **Certificates are checked.** Ovo never turns off HTTPS certificate checks.
- **Replies are not trusted.** Whatever a service sends back is checked before use: numbers must be numbers (kept between 0 and 100), times must be real times, and everything is shown as plain text, never as page code. An odd reply can't crash a check or run anything.
- **The windows are locked down.** Ovo's own pages carry a content security policy that lets them load nothing from the network, so even a bug could not send data out. The embedded browser runs with no debugging port, no `file://` pages, no downloads, and with QUIC switched off so it opens no UDP socket.
- **Your name can't break the page.** The name you type is escaped before it is placed in a page, so text like `</script>` is just text.
- **Fixed commands only.** The only programs Ovo starts are itself (to restart after a settings change or an update) and PowerShell (for the optional Start Menu shortcut), and, if you press Update while running from source, your browser to open the release page. Paths are quoted. Nothing from the network or from the page is ever run.
- **One change to Windows, and only if you ask.** The optional "Start with Windows" option adds one value to your own account's `Run` key, and unticking it removes it.

## What it can't protect against

- Someone who already controls your Windows account can read your Claude login and `~/.codex/auth.json`. That is true of those files with or without Ovo.
- Ovo uses internal endpoints that the services can change. If they do, it stops working; it doesn't fall back to anything riskier.
- The packaged `Ovo.exe` isn't code-signed. You can read the whole program (`ovo.pyw`) and build the exe yourself with `python tools/build.py`.

## Sharing safely

- Never share the `data/` folder or `%APPDATA%\Ovo`. They hold a login.
- Never paste `~/.codex/auth.json` or any token into an issue.
