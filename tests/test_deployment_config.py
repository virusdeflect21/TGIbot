from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RenderBlueprintTests(unittest.TestCase):
    def test_disk_backed_service_omits_unsupported_shutdown_delay(self) -> None:
        blueprint = (REPOSITORY_ROOT / "render.yaml").read_text(encoding="utf-8")

        self.assertIn("mountPath: /var/data", blueprint)
        self.assertNotRegex(
            blueprint,
            re.compile(r"(?m)^\s*maxShutdownDelaySeconds\s*:"),
        )


if __name__ == "__main__":
    unittest.main()
