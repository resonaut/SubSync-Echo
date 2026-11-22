"""The release page text (.github/release_notes.py): the Highlights of a
version and a link to its whole section of CHANGELOG.md.

    python -m unittest discover -s tests -v
"""

import importlib.util
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
_spec = importlib.util.spec_from_file_location('release_notes', os.path.join(ROOT, '.github', 'release_notes.py'))
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)

TEMPLATE = '<!-- comment -->\nIntro.\n\n## New in {{VERSION}}\n\n{{HIGHLIGHTS}}\n\n[All]({{CHANGES_URL}})\n'
CHANGELOG = '''# Changelog

## [0.21] - 2026-11-23

### Highlights
- **One.** First point.
- **Two.** Second point, see [the guide](doc/guide.md) and [the site](https://example.com).

### Fixed
- A long technical entry.

## [0.20] - 2026-11-15

### Fixed
- Older.

[0.21]: https://example.com
'''


def read(*path):
    with open(os.path.join(ROOT, *path), encoding='utf-8') as fp:
        return fp.read()


class ReleaseNotesTest(unittest.TestCase):
    def test_highlights_and_link(self):
        body, error = rn.notes(CHANGELOG, TEMPLATE, '0.21')
        self.assertIsNone(error)
        self.assertIn('- **One.** First point.\n- **Two.** Second point', body)
        self.assertIn('[the guide](https://github.com/resonaut/SubSync-Echo/blob/0.21/doc/guide.md)', body,
                      "links to the repository's files work from the release page")
        self.assertIn('[the site](https://example.com)', body)
        self.assertNotIn('technical', body, 'only the highlights')
        self.assertIn('/blob/0.21/CHANGELOG.md#021---2026-11-23', body)
        self.assertTrue(body.startswith('Intro.'), 'the comment is left out')
        self.assertNotIn('{{', body)

    def test_version_without_highlights_refused(self):
        body, error = rn.notes(CHANGELOG, TEMPLATE, '0.20')
        self.assertIsNone(body)
        self.assertIn('no Highlights for 0.20', error)

    def test_version_without_section_refused(self):
        body, error = rn.notes(CHANGELOG, TEMPLATE, '0.22')
        self.assertIsNone(body)
        self.assertIn('no entry for 0.22', error)

    def test_github_heading_links(self):
        self.assertEqual(rn.anchor('## [0.21] - 2026-11-23'), '021---2026-11-23')
        self.assertEqual(rn.anchor('## [Unreleased]'), 'unreleased')

    def test_the_next_release_page(self):
        # the real CHANGELOG and template, with Unreleased named as a release
        changelog = re.sub(r'^## \[Unreleased\]', '## [9.99] - 2026-12-31', read('CHANGELOG.md'),
                           count=1, flags=re.MULTILINE)
        body, error = rn.notes(changelog, read('.github', 'release-notes.md'), '9.99')
        self.assertIsNone(error, 'Unreleased needs Highlights before the next release')
        self.assertNotIn('{{', body)
        self.assertIn('#999---2026-12-31', body)
        self.assertLess(len(body.split()), 600, 'a short page')


if __name__ == '__main__':
    unittest.main()
