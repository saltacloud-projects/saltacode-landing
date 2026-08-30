from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def load_module(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CommitMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module("validate_commits", "scripts/agentic/validate-commits.py")

    def test_accepts_conventional_subject(self) -> None:
        self.assertEqual(self.module.message_errors("feat(api): stream replies"), [])
        self.assertEqual(self.module.message_errors("fix!: preserve contracts"), [])

    def test_rejects_non_conventional_subject(self) -> None:
        self.assertIn(
            "subject is not a Conventional Commit",
            self.module.message_errors("update files"),
        )

    def test_rejects_attribution(self) -> None:
        self.assertIn(
            "Co-Authored-By trailers are forbidden",
            self.module.message_errors(
                "chore: test\n\nCo-Authored-By: Example <example@example.com>"
            ),
        )
        self.assertIn(
            "AI attribution is forbidden",
            self.module.message_errors("chore: test\n\nGenerated with Codex"),
        )


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module("agentic_doctor", "scripts/agentic/doctor.py")

    def test_manifest_has_all_classifications(self) -> None:
        requirements = self.module.load_requirements(
            ROOT / "scripts/agentic/tool-requirements.toml"
        )
        self.assertEqual(
            {item.classification for item in requirements},
            {"required", "recommended", "external"},
        )


class CommitRangeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        self.run_git("init", "--quiet")
        self.run_git("config", "user.name", "Contract Test")
        self.run_git("config", "user.email", "contract@example.invalid")
        self.good_commit = self.commit("feat(test): add fixture")
        self.bad_commit = self.commit("update fixture")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repository), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def commit(self, message: str) -> str:
        marker = self.repository / "fixture.txt"
        marker.write_text(message, encoding="utf-8")
        self.run_git("add", "fixture.txt")
        self.run_git("commit", "--quiet", "-m", message)
        return self.run_git("rev-parse", "HEAD").stdout.strip()

    def validate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(ROOT / "scripts/agentic/validate-commits.py"),
                "--repository",
                str(self.repository),
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_exact_commit_and_range_outcomes(self) -> None:
        self.assertEqual(
            self.validate("--commits", self.good_commit).returncode,
            0,
        )
        result = self.validate("--range", self.good_commit, self.bad_commit)
        self.assertEqual(result.returncode, 1)
        self.assertIn("subject is not a Conventional Commit", result.stderr)

    def test_zero_base_requires_explicit_boundary(self) -> None:
        result = self.validate("--range", "0" * 40, self.bad_commit)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--new-branch-base", result.stderr)


if __name__ == "__main__":
    unittest.main()
