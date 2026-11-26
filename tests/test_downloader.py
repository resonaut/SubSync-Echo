"""Unit tests for subsync/assets/downloader.py and subsync/pubkey.py: an asset
is installed only when its signature downloads and matches, and each failure
says which step failed.

    python -m unittest discover -s tests -v

Needs the app's packages (requests, the compiled engine), so it runs with the
app's Python and in the release builds, and is skipped elsewhere.
"""

import io
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    import builtins
    builtins.__dict__.setdefault('_', lambda s: s)
    import requests
    from subsync import config, pubkey
    from subsync.assets import downloader
    from subsync.error import Error
except ImportError:         # the app's packages aren't installed
    downloader = None


ASSET_URL = 'https://example.invalid/asset.zip'
SIG_URL = 'https://example.invalid/asset.zip.sig'


def zipBytes(*names):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        for name in names:
            z.writestr(zipfile.ZipInfo(name), b'x')
    return data.getvalue()


class Response(object):
    def __init__(self, content):
        self.content = content
        self.headers = {'content-length': str(len(content))}

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i+size]


class FakeAsset(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._local = None
        self.removed = 0

    def getId(self):
        return 'test/asset'

    def hasUpdate(self):
        return True

    def _getRemoteData(self):
        return {'url': ASSET_URL, 'sig': SIG_URL, 'type': 'zip'}

    def _removeLocalData(self):
        self.removed += 1


@unittest.skipIf(downloader is None, "SubSync's packages not installed")
class DownloaderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assetdir = os.path.join(tmp.name, 'assets')
        patcher = mock.patch.object(config, 'assetdir', self.assetdir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def download(self, archive, signature=None, verify=None):
        """Runs the downloader with the network and the signature check
        replaced; returns (asset, exception or None)."""
        def get(url, **kw):
            if url == SIG_URL:
                if isinstance(signature, Exception):
                    raise signature
                return Response(signature or b'sig')
            return Response(archive)

        asset = FakeAsset()
        with mock.patch.object(downloader.requests, 'get', side_effect=get), \
             mock.patch.object(downloader.pubkey, 'verify', verify or (lambda h, s: None)):
            d = downloader.AssetDownloader(asset)
            d.run()
            d.wait()
        return asset, d._exception and d._exception[1]

    def installed(self):
        return sorted(os.listdir(self.assetdir)) if os.path.isdir(self.assetdir) else []

    def test_good_asset_installed(self):
        asset, err = self.download(zipBytes('eng.dict', 'models/eng/model.bin'))
        self.assertIsNone(err)
        self.assertEqual(self.installed(), ['eng.dict', 'models'])

    def test_signature_download_failure_reported_as_such(self):
        asset, err = self.download(zipBytes('eng.dict'),
                signature=requests.ConnectionError('network down'))
        self.assertIsInstance(err, Error)
        self.assertEqual(err.message, "Couldn't download asset signature")
        self.assertIn('network down', err.fields['reason'])
        self.assertEqual(self.installed(), [])
        self.assertEqual(asset.removed, 0, 'the installed asset must be kept')

    def test_signature_mismatch_reported_as_such(self):
        def verify(hash, sig):
            raise ValueError('signature does not match')
        asset, err = self.download(zipBytes('eng.dict'), verify=verify)
        self.assertIsInstance(err, Error)
        self.assertEqual(err.message, 'Signature verification failed')
        self.assertIn('signature does not match', err.fields['reason'])
        self.assertEqual(self.installed(), [])
        self.assertEqual(asset.removed, 0, 'the installed asset must be kept')

    def test_bad_archive_not_installed(self):
        asset, err = self.download(zipBytes('eng.dict', '../evil.txt'))
        self.assertIsInstance(err, Error)
        self.assertEqual(err.message, 'Asset installation failed')
        self.assertFalse(os.path.exists(os.path.join(self.assetdir, '..', 'evil.txt')))
        self.assertGreaterEqual(asset.removed, 1, 'a half-installed asset must be removed')


@unittest.skipIf(downloader is None, "SubSync's packages not installed")
class SignatureTest(unittest.TestCase):
    """pubkey.verify with a real RSA key, whichever library the app uses."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        keypath = os.path.join(tmp.name, 'key.pub')
        if pubkey.verify is pubkey.verify_crypto:
            from Crypto.PublicKey import RSA
            from Crypto.Signature import PKCS1_v1_5
            key = RSA.generate(2048)
            with open(keypath, 'wb') as fp:
                fp.write(key.publickey().exportKey('PEM'))
            self.sign = lambda h: PKCS1_v1_5.new(key).sign(h)
        else:
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import rsa, padding, utils
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with open(keypath, 'wb') as fp:
                fp.write(key.public_key().public_bytes(serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo))
            self.sign = lambda h: key.sign(h.digest(), padding.PKCS1v15(),
                    utils.Prehashed(hashes.SHA256()))
        for name, value in (('keypath', keypath),):
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(pubkey, '_pubkey', None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hashOf(self, data):
        h = pubkey.sha256()
        h.update(data)
        return h

    def test_matching_signature_accepted(self):
        pubkey.verify(self.hashOf(b'asset'), self.sign(self.hashOf(b'asset')))

    def test_other_data_refused(self):
        with self.assertRaises(Exception):
            pubkey.verify(self.hashOf(b'changed asset'), self.sign(self.hashOf(b'asset')))


if __name__ == '__main__':
    unittest.main()
