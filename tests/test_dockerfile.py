from __future__ import annotations

import unittest
from pathlib import Path


class DockerfileTests(unittest.TestCase):
    def test_command_uses_configured_uv_environment(self) -> None:
        dockerfile = Path(__file__).parent.parent.joinpath("Dockerfile").read_text()

        self.assertIn("UV_PROJECT_ENVIRONMENT=/app/.venv", dockerfile)
        self.assertIn('CMD ["/app/.venv/bin/python", "/app/handler.py"]', dockerfile)


if __name__ == "__main__":
    unittest.main()
