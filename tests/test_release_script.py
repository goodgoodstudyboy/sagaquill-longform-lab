from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release_script", SCRIPT_PATH)
assert SPEC is not None
release_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = release_script
SPEC.loader.exec_module(release_script)


class ReleaseScriptTests(unittest.TestCase):
    def test_normalize_version_accepts_plain_and_tagged_versions(self) -> None:
        self.assertEqual(release_script.normalize_version("0.7.2"), ("0.7.2", "v0.7.2"))
        self.assertEqual(release_script.normalize_version("v0.7.2"), ("0.7.2", "v0.7.2"))

    def test_normalize_version_rejects_ambiguous_values(self) -> None:
        with self.assertRaises(release_script.ReleaseError):
            release_script.normalize_version("release-0.7.2")

    def test_parse_github_repo_slug_accepts_common_remote_forms(self) -> None:
        self.assertEqual(
            release_script.parse_github_repo_slug("https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git"),
            "goodgoodstudyboy/sagaquill-longform-lab",
        )
        self.assertEqual(
            release_script.parse_github_repo_slug("https://goodgoodstudyboy@github.com/goodgoodstudyboy/sagaquill-longform-lab.git"),
            "goodgoodstudyboy/sagaquill-longform-lab",
        )
        self.assertEqual(
            release_script.parse_github_repo_slug("git@github.com:goodgoodstudyboy/sagaquill-longform-lab.git"),
            "goodgoodstudyboy/sagaquill-longform-lab",
        )
        self.assertEqual(
            release_script.parse_github_repo_slug("ssh://git@github.com/goodgoodstudyboy/sagaquill-longform-lab"),
            "goodgoodstudyboy/sagaquill-longform-lab",
        )

    def test_replace_project_version_updates_single_version_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text(
                '\n'.join(
                    [
                        "[project]",
                        'name = "sagaquill"',
                        'version = "0.7.1"',
                        'description = "test"',
                    ]
                ),
                encoding="utf-8",
            )

            changed = release_script.replace_project_version("0.7.2", path)

            self.assertTrue(changed)
            self.assertIn('version = "0.7.2"', path.read_text(encoding="utf-8"))

    def test_build_release_body_includes_checks_and_docker_tags(self) -> None:
        body = release_script.build_release_body(
            repo="goodgoodstudyboy/sagaquill-longform-lab",
            tag="v0.7.2",
            previous_tag="v0.7.1",
            checks=["python -m unittest discover -s tests -v"],
            notes_file=None,
        )

        self.assertIn("Changes since `v0.7.1`", body)
        self.assertIn("python -m unittest discover -s tests -v", body)
        self.assertIn("ghcr.io/goodgoodstudyboy/sagaquill-longform-lab:v0.7.2", body)


if __name__ == "__main__":
    unittest.main()
