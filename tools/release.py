"""Publish a new version of Ovo.

    python tools/release.py 1.1.0            check everything, bump the version, commit, tag v1.1.0 and push
    python tools/release.py 1.1.0 --dry-run  check, and show what it would do without changing anything
    python tools/release.py --notes 1.1.0    print the release notes for 1.1.0 (the build workflow uses this)

Before running it, add a "## 1.1.0 - date" section to CHANGELOG.md. Pushing the tag starts the "Release" workflow
on GitHub, which builds Ovo.exe, writes the checksum and publishes the release. People running Ovo are then offered
the update the next time it checks.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP, CHANGELOG, README = ROOT / 'ovo.pyw', ROOT / 'CHANGELOG.md', ROOT / 'README.md'
VERSION_LINE = re.compile(r"^VERSION = '([^']+)'", re.M)
BADGE = re.compile(r'(badge/release-)\d+\.\d+\.\d+(-)')  # the release badge at the top of the README


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


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, check=check, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description='Publish a new version of Ovo.')
    parser.add_argument('version', help='the new version, like 1.1.0')
    parser.add_argument('--notes', action='store_true', help='only print the release notes for that version')
    parser.add_argument('--dry-run', action='store_true', help='check everything but change nothing')
    parser.add_argument('--yes', action='store_true', help="don't ask before pushing")
    args = parser.parse_args()
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
    if not BADGE.search(README.read_text(encoding='utf-8')):
        raise SystemExit('README.md has no release badge (badge/release-X.Y.Z-...) to update.')
    if subprocess.run([sys.executable, str(APP), '--test'], cwd=ROOT).returncode:
        raise SystemExit('The self-test failed, so nothing was released.')

    print(f'Releasing {current_version()} -> {args.version}\n\nRelease notes:\n{notes}\n')
    if args.dry_run:
        print('Dry run: everything checks out. Nothing was changed.')
        return
    if not args.yes and input('Commit, tag and push now? [y/N] ').strip().lower() != 'y':
        raise SystemExit('Cancelled.')
    APP.write_text(VERSION_LINE.sub(f"VERSION = '{args.version}'", APP.read_text(encoding='utf-8'), count=1), encoding='utf-8')
    README.write_text(BADGE.sub(rf'\g<1>{args.version}\g<2>', README.read_text(encoding='utf-8'), count=1), encoding='utf-8')
    git('commit', '-am', f'Release {args.version}')
    git('tag', '-a', f'v{args.version}', '-m', f'Ovo {args.version}')
    git('push', 'origin', 'main', f'v{args.version}')
    print(f'Pushed v{args.version}. GitHub is building it now: watch the Actions tab. Once the release is published, '
          'people running Ovo are offered the update.')


if __name__ == '__main__':
    main()
