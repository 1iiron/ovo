"""Publish a new version of Ovo.

    python tools/release.py 1.1.0            check everything, bump the version, commit, tag v1.1.0 and push
    python tools/release.py 1.1.0 --dry-run  check, and show what it would do without changing anything
    python tools/release.py --notes 1.1.0    print the release notes for 1.1.0 (the build workflow uses this)
    python tools/release.py --selftest       check the README rewriting on a sample

Before running it, add a "## 1.1.0 - date" section to CHANGELOG.md. Pushing the tag starts the "Release" workflow
on GitHub, which builds Ovo.exe, writes the checksum and publishes the release. People running Ovo are then offered
the update the next time it checks.

The README text that mentions the latest release is rewritten for you in the same commit: the badge, the "Latest
release" box (version, date, what's new, download link) and the download link in the install steps.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = '1iiron/ovo'
APP, CHANGELOG, README = ROOT / 'ovo.pyw', ROOT / 'CHANGELOG.md', ROOT / 'README.md'
VERSION_LINE = re.compile(r"^VERSION = '([^']+)'", re.M)
# The three places in the README that are rewritten on every release.
BADGE = re.compile(r'(badge/release-)\d+\.\d+\.\d+(-)')
BLOCK = re.compile(r'(<!-- latest-release:start -->\n).*?(\n<!-- latest-release:end -->)', re.S)
ZIP_LINK = re.compile(r'(<!-- zip:start -->).*?(<!-- zip:end -->)')


def as_tuple(version):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', version)
    return tuple(map(int, match.groups())) if match else None


def current_version():
    return VERSION_LINE.search(APP.read_text(encoding='utf-8')).group(1)


def notes_for(version):
    """The text under '## <version>' in CHANGELOG.md, up to the next '## ' heading."""
    text = CHANGELOG.read_text(encoding='utf-8')
    match = re.search(rf'^## {re.escape(version)}(?:[ \t][^\n]*)?\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    notes = match.group(1).strip() if match else ''
    if not notes:
        raise SystemExit(f'CHANGELOG.md has no notes for {version}. Add a "## {version} - date" section first.')
    return notes


def release_date(version):
    """The date written in the CHANGELOG heading ('## 1.1.0 - 2026-12-01'), or today's if there isn't one."""
    match = re.search(rf'^## {re.escape(version)} - (\d{{4}}-\d{{2}}-\d{{2}})', CHANGELOG.read_text(encoding='utf-8'), re.M)
    return match.group(1) if match else date.today().isoformat()


def rewrite_readme(text, version, day, notes):
    """The README with its release text rewritten for this version: the badge, the "Latest release" box and the
    download link. Exits if one of the three places is missing, so a release never leaves old text behind."""
    tag, zip_name = f'v{version}', f'Ovo-{version}-windows.zip'
    base = f'https://github.com/{REPO}/releases'
    box = (f'**Latest release: [Ovo {version}]({base}/tag/{tag})** · {day} · '
           f'[Download for Windows]({base}/download/{tag}/{zip_name})\n\n{notes}')
    text, badges = BADGE.subn(rf'\g<1>{version}\g<2>', text, count=1)
    text, boxes = BLOCK.subn(lambda m: m.group(1) + box + m.group(2), text, count=1)
    text, links = ZIP_LINK.subn(lambda m: m.group(1) + f'[{zip_name}]({base}/download/{tag}/{zip_name})' + m.group(2),
                                text, count=1)
    if (badges, boxes, links) != (1, 1, 1):
        raise SystemExit('README.md needs the release badge, the latest-release markers and the zip-link markers.')
    return text


def self_test():
    sample = ('![](badge/release-1.0.0-x)\n<!-- latest-release:start -->\nold text\n<!-- latest-release:end -->\n'
              '1. Download <!-- zip:start -->old.zip<!-- zip:end --> now\n')
    out = rewrite_readme(sample, '1.2.3', '2026-12-01', '- one\n- two')
    for wanted in ('badge/release-1.2.3-x', 'Ovo 1.2.3', '/tag/v1.2.3', '2026-12-01', '- two', 'old.zip' not in out and 'now',
                   f'[Ovo-1.2.3-windows.zip](https://github.com/{REPO}/releases/download/v1.2.3/Ovo-1.2.3-windows.zip)'):
        assert wanted and (wanted is True or wanted in out), wanted
    again = rewrite_readme(out, '1.2.4', '2026-12-02', '- three')
    assert '1.2.3' not in again and '- two' not in again and 'Ovo 1.2.4' in again  # nothing stale is left behind
    try:
        rewrite_readme('no markers here', '1.2.4', '2026-12-02', 'x')
        raise AssertionError('accepted a README without the markers')
    except SystemExit:
        pass
    assert as_tuple('1.10.0') > as_tuple('1.9.9') and as_tuple('1.0') is None
    print('ok')


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, check=check, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description='Publish a new version of Ovo.')
    parser.add_argument('version', nargs='?', help='the new version, like 1.1.0')
    parser.add_argument('--notes', action='store_true', help='only print the release notes for that version')
    parser.add_argument('--selftest', action='store_true', help='check the README rewriting on a sample')
    parser.add_argument('--dry-run', action='store_true', help='check everything but change nothing')
    parser.add_argument('--yes', action='store_true', help="don't ask before pushing")
    args = parser.parse_args()
    if args.selftest:
        return self_test()
    if not args.version:
        parser.error('give the new version, like 1.1.0')
    if args.notes:
        sys.stdout.reconfigure(encoding='utf-8')
        print(notes_for(args.version))
        return

    new, old = as_tuple(args.version), as_tuple(current_version())
    if not new:
        raise SystemExit('The version must look like 1.1.0 (three numbers).')
    if new <= old:
        raise SystemExit(f'{args.version} is not newer than the current version {current_version()}.')
    if git('rev-parse', '--abbrev-ref', 'HEAD') != 'main':
        raise SystemExit('Release from the main branch.')
    if git('status', '--porcelain'):
        raise SystemExit('There are uncommitted changes. Commit or stash them first.')
    git('fetch', 'origin')
    if git('rev-list', '--count', 'HEAD..origin/main') != '0':
        raise SystemExit('main is behind GitHub. Pull first.')
    if git('tag', '--list', f'v{args.version}'):
        raise SystemExit(f'The tag v{args.version} already exists.')
    notes = notes_for(args.version)
    rewrite_readme(README.read_text(encoding='utf-8'), args.version, release_date(args.version), notes)  # fails early
    if subprocess.run([sys.executable, str(APP), '--test'], cwd=ROOT).returncode:
        raise SystemExit('The self-test failed, so nothing was released.')

    print(f'Releasing {current_version()} -> {args.version}\n\nRelease notes:\n{notes}\n')
    if args.dry_run:
        print('Dry run: everything checks out. Nothing was changed.')
        return
    if not args.yes and input('Commit, tag and push now? [y/N] ').strip().lower() != 'y':
        raise SystemExit('Cancelled.')
    APP.write_text(VERSION_LINE.sub(f"VERSION = '{args.version}'", APP.read_text(encoding='utf-8'), count=1), encoding='utf-8')
    README.write_text(rewrite_readme(README.read_text(encoding='utf-8'), args.version, release_date(args.version), notes),
                      encoding='utf-8')
    git('commit', '-am', f'Release {args.version}')
    git('tag', '-a', f'v{args.version}', '-m', f'Ovo {args.version}')
    git('push', 'origin', 'main', f'v{args.version}')
    print(f'Pushed v{args.version}. GitHub is building it now: watch the Actions tab. Once the release is published, '
          'people running Ovo are offered the update.')


if __name__ == '__main__':
    main()
