from __future__ import annotations

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RenderManualDeploymentTests(unittest.TestCase):
    def test_render_deployment_is_documented_without_a_blueprint(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertFalse((REPOSITORY_ROOT / "render.yaml").exists())
        self.assertIn("Deploy to Render manually (no Blueprint)", readme)
        self.assertIn("New → Web Service", readme)
        self.assertIn("uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1", readme)
        self.assertIn("/health", readme)


if __name__ == "__main__":
    unittest.main()
