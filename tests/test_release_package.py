from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_release import build_release_archive


class ReleaseArchiveTests(unittest.TestCase):
    def test_release_zip_has_app_guide_and_blank_config_template_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = build_release_archive("9.8.7", Path(temp_dir))

            self.assertEqual(archive_path.name, "TGIbot-local-v9.8.7.zip")
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())

        prefix = "TGIbot-local-v9.8.7/"
        self.assertIn(prefix + "app.py", names)
        self.assertIn(prefix + "LOCAL_SETUP.md", names)
        self.assertIn(prefix + "config.example.py", names)
        self.assertIn(prefix + "requirements.txt", names)
        self.assertTrue(all(name.startswith(prefix) for name in names))
        self.assertFalse(any(name.endswith("/config.py") for name in names))
        self.assertFalse(any(name.endswith(".session") for name in names))
        self.assertFalse(any("/data/" in name for name in names))

    def test_invalid_release_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "version must look like"):
                build_release_archive("../../secrets", Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
