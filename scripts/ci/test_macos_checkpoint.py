#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import macos_checkpoint as checkpoint


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_accepted_submission_is_stapled_without_another_upload(self):
        checkpoint.ensure(self.directory, "1.5.2", "cliente", "aarch64", "abc")
        checkpoint.record_notarization(self.directory, "submission-1", "Accepted", "notarized")
        self.assertEqual(checkpoint.notarization_action(checkpoint.load(self.directory)), "staple")
        saved = json.loads((self.directory / "checkpoint.json").read_text())
        self.assertEqual(saved["version"], "1.5.2")
        self.assertEqual(saved["edition"], "cliente")
        self.assertEqual(saved["arch"], "aarch64")
        self.assertEqual(saved["origin"], "abc")

    def test_in_progress_submission_waits_and_invalid_submits_again(self):
        checkpoint.record_notarization(self.directory, "submission-1", "In Progress", "notarized")
        self.assertEqual(checkpoint.notarization_action(checkpoint.load(self.directory)), "wait")
        checkpoint.record_notarization(self.directory, "submission-1", "Invalid", "notarized")
        self.assertEqual(checkpoint.notarization_action(checkpoint.load(self.directory)), "submit")
        self.assertEqual(checkpoint.notarization_action({}), "submit")

    def test_file_hash_is_required_to_resume(self):
        payload = self.directory / "signed.dmg"
        payload.write_bytes(b"signed image")
        checkpoint.add_file(self.directory, "signed.dmg", "signed")
        self.assertEqual(checkpoint.verify_file(self.directory, "signed.dmg"), payload)
        payload.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            checkpoint.verify_file(self.directory, "signed.dmg")
        self.assertEqual(hashlib.sha256(b"signed image").hexdigest(),
                         json.loads((self.directory / "checkpoint.json").read_text())["files"]["signed.dmg"]["sha256"])

    def test_stage_does_not_move_backwards(self):
        payload = self.directory / "app.tar"
        payload.write_bytes(b"app")
        checkpoint.add_file(self.directory, "app.tar", "compiled")
        signed = self.directory / "signed.dmg"
        signed.write_bytes(b"dmg")
        checkpoint.add_file(self.directory, "signed.dmg", "signed")
        checkpoint.add_file(self.directory, "app.tar", "compiled")
        self.assertEqual(checkpoint.load(self.directory)["stage"], "signed")


if __name__ == "__main__":
    unittest.main()
