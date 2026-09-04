from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from client_update.config import UpdateConfig
from client_update.errors import UpdateError
from client_update.health import mark_update_healthy
from client_update.security import artifact_canonical, policy_canonical, verify_ed25519
from client_update.updater import safe_extract


class ClientUpdateTest(unittest.TestCase):
    def test_project_config_matches_current_client(self):
        config = UpdateConfig.load()
        self.assertEqual(3, config.app_id)
        self.assertEqual("1.7.0", config.version)
        self.assertEqual("zhibodou.exe", config.entry_point)
        self.assertEqual("zhibodou_updater.exe", config.updater_executable)
        self.assertIn("client-release-2026-01", config.artifact_public_keys)

    def test_config_rejects_unsafe_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.json"
            source.write_text(json.dumps({
                "appId": 3, "version": "1.7.0", "updaterVersion": "1.0.0",
                "entryPoint": "../outside.exe", "serverBaseUrl": "https://example.com",
            }), encoding="utf-8")
            with self.assertRaises(UpdateError):
                UpdateConfig.load(source)

    def test_policy_and_artifact_signatures_are_bound_to_metadata(self):
        private = Ed25519PrivateKey.generate()
        public = base64.b64encode(private.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo,
        )).decode("ascii")
        policy = {
            "protocolVersion": 1, "appId": 3, "channel": "STABLE",
            "platform": "WINDOWS", "arch": "X64", "policyRevision": 2,
            "updatePolicy": "OPTIONAL", "minimumSupportedVersion": None,
            "mandatoryReleaseId": None, "targetVersion": "1.8.0",
            "policyIssuedAt": "2026-09-02T10:00:00", "policyExpiresAt": "2026-09-03T10:00:00",
        }
        canonical = policy_canonical(policy)
        signature = base64.b64encode(private.sign(canonical.encode())).decode("ascii")
        verify_ed25519(canonical, signature, public, "策略")
        with self.assertRaises(UpdateError):
            verify_ed25519(canonical.replace("1.8.0", "1.9.0"), signature, public, "策略")

        artifact = {"platform": "WINDOWS", "arch": "X64", "packageType": "ZIP",
                    "fileSize": 123, "sha256": "a" * 64}
        canonical = artifact_canonical(3, "1.8.0", artifact)
        signature = base64.b64encode(private.sign(canonical.encode())).decode("ascii")
        verify_ed25519(canonical, signature, public, "构件")

    def test_safe_extract_blocks_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "bad.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../escape.txt", "bad")
                archive.writestr("update-manifest.json", "{}")
            args = Namespace(app_id=3, version="1.8.0", platform="WINDOWS", arch="X64",
                             entry_point="zhibodou.exe")
            with self.assertRaises(SystemExit):
                safe_extract(package, root / "target", args)
            self.assertFalse((root / "escape.txt").exists())

    def test_health_marker_requires_matching_nonce(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "health.json"
            with patch.dict(os.environ, {
                "PDK_UPDATE_HEALTH_FILE": str(marker),
                "PDK_UPDATE_HEALTH_NONCE": "nonce-1",
            }, clear=False):
                self.assertTrue(mark_update_healthy("1.8.0"))
            data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual({"version": "1.8.0", "nonce": "nonce-1"},
                             {"version": data["version"], "nonce": data["nonce"]})


if __name__ == "__main__":
    unittest.main()
