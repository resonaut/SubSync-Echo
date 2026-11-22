"""Write the release page text for a version.

Takes the Highlights of that version's section of CHANGELOG.md and puts them
into the .github/release-notes.md template, with a link to the whole section
for everything else. Fails when the changelog has no section for the version,
or the section has no highlights, so a release can't be published without
them.

usage: python .github/release_notes.py VERSION [OUTPUT]
"""

import os
import re
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = 'https://github.com/resonaut/SubSync-Echo'


def section(text, version):
    """The heading line and the text of the version's section, from
    "## [version]" to the next "## [" heading or the link list."""
    match = re.search(r'^(## \[' + re.escape(version) + r'\][^\n]*)\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)',
            text, re.MULTILINE | re.DOTALL)
    return (match.group(1).strip(), match.group(2).strip()) if match else (None, '')


def highlights(body):
    """The bullet list under "### Highlights", up to the next heading."""
    match = re.search(r'^### Highlights[ \t]*\n(.*?)(?=^#|\Z)', body, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ''


def anchor(heading):
    """The link GitHub gives a heading: its text as shown (links keep their
    text), lower case, without punctuation, with a hyphen for each space.
    "## [0.21] - 2026-11-23" becomes "021---2026-11-23"."""
    text = re.sub(r'^#+\s*', '', heading)
    text = re.sub(r'\[([^\]]*)\]', r'\1', text).lower()
    text = re.sub(r'[^\w\- ]', '', text)
    return text.replace(' ', '-')


def notes(changelog, template, version):
    """The release page text, or an error message (str) and None."""
    heading, body = section(changelog, version)
    if heading is None:
        return None, ('CHANGELOG.md has no entry for {}: rename "Unreleased" to "{}" '
                'with the date before tagging'.format(version, version))
    points = highlights(body)
    if not points:
        return None, ('CHANGELOG.md has no Highlights for {}: start its section with '
                '"### Highlights" and a few plain-words points'.format(version))
    # links to the repository's files (doc/guide.md) would point nowhere from
    # the release page: they get the repository address, at this version
    points = re.sub(r'\]\((?![a-z]+:|#)([^)]+)\)',
            lambda m: ']({}/blob/{}/{})'.format(REPO, version, m.group(1)), points)
    url = '{}/blob/{}/CHANGELOG.md#{}'.format(REPO, version, anchor(heading))
    template = re.sub(r'\A<!--.*?-->\s*', '', template, flags=re.DOTALL)
    return (template.replace('{{HIGHLIGHTS}}', points).replace('{{CHANGES_URL}}', url)
            .replace('{{VERSION}}', version)), None


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    with open(os.path.join(root, 'CHANGELOG.md'), encoding='utf-8') as fp:
        changelog = fp.read()
    with open(os.path.join(root, '.github', 'release-notes.md'), encoding='utf-8') as fp:
        template = fp.read()
    body, error = notes(changelog, template, argv[1])
    if error:
        print(error, file=sys.stderr)
        return 1

    if len(argv) > 2:
        with open(argv[2], 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(body)
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(body)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
