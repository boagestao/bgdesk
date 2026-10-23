import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import generate_update_metadata as metadata


class LatestMetadataTests(unittest.TestCase):
    def test_python_published_signature_vector_and_tampering(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/signed_latest.json').read_bytes())
        data, signature = metadata.read_latest(json.dumps(fixture['latest']).encode())
        with patch.dict(os.environ, {metadata.PUBLIC_KEY_ENV: fixture['public_key']}), \
                patch.object(metadata, 'KEY_ID', 'test-ed25519-main'):
            metadata.verify_metadata_signature(data, signature)
            with self.assertRaises(SystemExit):
                metadata.verify_metadata_signature(data + b' ', signature)
        self.assertIn('Atualização'.encode(), data)

    def test_unsigned_pointer_is_not_a_latest_manifest(self):
        for data in (b'{"url":"https://bgdesk.com"}', b'{"version":"1.5.1-3"}'):
            with self.assertRaises(SystemExit):
                metadata.read_latest(data)


if __name__ == '__main__':
    unittest.main()
