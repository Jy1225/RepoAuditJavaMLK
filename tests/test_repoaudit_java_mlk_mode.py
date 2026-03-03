import argparse
import sys
import unittest
from pathlib import Path


REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from repoaudit import RepoAudit  # noqa: E402


def _build_args(**overrides) -> argparse.Namespace:
    base = {
        "scan_type": "dfbscan",
        "project_path": ".",
        "language": "Java",
        "max_symbolic_workers": 1,
        "model_name": None,
        "temperature": 0.5,
        "call_depth": 3,
        "max_neural_workers": 1,
        "bug_type": "MLK",
        "is_reachable": False,
        "java_mlk_mode": "hybrid",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class RepoAuditJavaMLKModeValidationTests(unittest.TestCase):
    def _validate(self, args: argparse.Namespace):
        repoaudit = RepoAudit.__new__(RepoAudit)
        repoaudit.args = args
        return repoaudit.validate_inputs()

    def test_java_mlk_hybrid_requires_model_name(self) -> None:
        is_valid, errors = self._validate(_build_args(java_mlk_mode="hybrid"))
        self.assertFalse(is_valid)
        self.assertTrue(any("--model-name is required" in err for err in errors))

    def test_java_mlk_symbolic_does_not_require_model_name(self) -> None:
        is_valid, errors = self._validate(_build_args(java_mlk_mode="symbolic"))
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_non_java_mlk_still_requires_model_name(self) -> None:
        is_valid, errors = self._validate(_build_args(bug_type="NPD"))
        self.assertFalse(is_valid)
        self.assertTrue(any("--model-name is required" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
