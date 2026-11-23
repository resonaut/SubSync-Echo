"""Write the WinGet manifests for a published release of SubSync Echo.

WinGet installs the release's Windows zip as a portable app: it unpacks the
zip and adds the commands `subsync-echo` (the app) and `subsync-echo-cmd` (command
line). The manifests give the zip's address and SHA-256, so they can only be
written once the release is published; GitHub lists the SHA-256 of each
release file, so nothing is downloaded.

    python .github/winget_manifests.py 0.21 [OUTPUT_FOLDER]

writes OUTPUT_FOLDER/manifests/r/resonaut/SubSyncEcho/0.21/ (default output
folder: winget), the layout of microsoft/winget-pkgs. Check them with
`winget validate --manifest <that folder>`; to publish, copy the folder into a
fork of microsoft/winget-pkgs and open a pull request there.
"""

import json
import os
import sys
import urllib.request

REPO = 'resonaut/SubSync-Echo'
PACKAGE = 'resonaut.SubSyncEcho'
SCHEMA = '1.28.0'


def zipFile(version):
    """Address and SHA-256 of the release's Windows zip."""
    url = 'https://api.github.com/repos/{}/releases/tags/{}'.format(REPO, version)
    req = urllib.request.Request(url, headers={ 'Accept': 'application/vnd.github+json',
                                                'User-Agent': 'subsync-winget-manifests' })
    with urllib.request.urlopen(req) as fp:
        release = json.load(fp)
    name = 'subsync-{}-windows-x64.zip'.format(version)
    for asset in release.get('assets', []):
        if asset['name'] == name:
            digest = asset.get('digest') or ''
            if not digest.startswith('sha256:'):
                raise SystemExit('GitHub gives no SHA-256 for ' + name)
            return asset['browser_download_url'], digest.split(':', 1)[1].upper()
    raise SystemExit('release {} has no {}'.format(version, name))


def manifests(version, url, sha256):
    head = '# yaml-language-server: $schema=https://aka.ms/winget-manifest.{}.' + SCHEMA + '.schema.json\n\n'
    ids = 'PackageIdentifier: {}\nPackageVersion: "{}"\n'.format(PACKAGE, version)
    tail = 'ManifestVersion: {}\n'.format(SCHEMA)
    home = 'https://github.com/' + REPO
    return {
        PACKAGE + '.yaml': head.format('version') + ids + (
            'DefaultLocale: en-US\n'
            'ManifestType: version\n') + tail,

        PACKAGE + '.installer.yaml': head.format('installer') + ids + (
            'InstallerType: zip\n'
            'NestedInstallerType: portable\n'
            'NestedInstallerFiles:\n'
            '- RelativeFilePath: subsync\\subsync.exe\n'
            '  PortableCommandAlias: subsync-echo\n'
            '- RelativeFilePath: subsync\\subsync-cmd.exe\n'
            '  PortableCommandAlias: subsync-echo-cmd\n'
            'MinimumOSVersion: 10.0.17763.0\n'
            'Installers:\n'
            '- Architecture: x64\n'
            '  InstallerUrl: {}\n'
            '  InstallerSha256: {}\n'
            'ManifestType: installer\n').format(url, sha256) + tail,

        PACKAGE + '.locale.en-US.yaml': head.format('defaultLocale') + ids + (
            'PackageLocale: en-US\n'
            'Publisher: resonaut\n'
            'PublisherUrl: https://github.com/resonaut\n'
            'PublisherSupportUrl: {home}/issues\n'
            'PackageName: SubSync Echo\n'
            'PackageUrl: {home}\n'
            'License: GPL-3.0\n'
            'LicenseUrl: {home}/blob/{v}/LICENSE\n'
            'ShortDescription: Syncs subtitles to a video\'s audio, in almost any language.\n'
            'Description: >-\n'
            '  SubSync Echo fixes subtitles that are out of sync with a video. It listens to what\n'
            '  is said and moves every line to the moment it is spoken: anime and other Japanese\n'
            '  films, English films, and subtitles in a different language from the audio.\n'
            '  Everything runs on your own computer, with no graphics card, and nothing is uploaded.\n'
            # sc0ty.SubSync (the original) already has the moniker subsync
            'Moniker: subsync-echo\n'
            'Tags:\n'
            '- subtitles\n'
            '- subtitle-sync\n'
            '- srt\n'
            '- whisper\n'
            '- anime\n'
            '- speech-recognition\n'
            'ReleaseNotesUrl: {home}/releases/tag/{v}\n'
            'Documentations:\n'
            '- DocumentLabel: User guide\n'
            '  DocumentUrl: {home}/blob/{v}/doc/guide.md\n'
            'ManifestType: defaultLocale\n').format(home=home, v=version) + tail,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    version = argv[1]
    out = os.path.join(argv[2] if len(argv) > 2 else 'winget', 'manifests', 'r', 'resonaut',
                       'SubSyncEcho', version)
    url, sha256 = zipFile(version)
    os.makedirs(out, exist_ok=True)
    for name, text in manifests(version, url, sha256).items():
        with open(os.path.join(out, name), 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(text)
    print('written to', out)
    print('check them: winget validate --manifest "{}"'.format(out))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
