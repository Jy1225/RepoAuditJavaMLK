import sys
import types
import unittest
from pathlib import Path


try:
    import tree_sitter  # noqa: F401
except ModuleNotFoundError:
    fake_tree_sitter = types.ModuleType("tree_sitter")

    class _DummyNode:
        pass

    class _DummyTree:
        pass

    class _DummyLanguage:
        def __init__(self, *args, **kwargs):
            pass

    class _DummyParser:
        def __init__(self, *args, **kwargs):
            pass

        def set_language(self, *args, **kwargs):
            return None

    fake_tree_sitter.Language = _DummyLanguage
    fake_tree_sitter.Node = _DummyNode
    fake_tree_sitter.Tree = _DummyTree
    fake_tree_sitter.Parser = _DummyParser
    sys.modules["tree_sitter"] = fake_tree_sitter


REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from tstool.analyzer.TS_analyzer import (  # noqa: E402
    CallContext,
    ContextLabel,
    Parenthesis,
)


class CallContextMatchingTests(unittest.TestCase):
    def _make_label(
        self,
        line_number: int,
        parenthesis: Parenthesis,
        file_name: str = "A.java",
        function_id: int = 1,
    ) -> ContextLabel:
        return ContextLabel(file_name, line_number, function_id, parenthesis)

    def test_forward_context_matches_left_then_right(self) -> None:
        context = CallContext(is_backward=False)
        left = self._make_label(10, Parenthesis.LEFT_PAR)
        right = self._make_label(10, Parenthesis.RIGHT_PAR)

        self.assertTrue(context.add_and_check_context(left))
        self.assertTrue(context.add_and_check_context(right))
        self.assertEqual(len(context.simplified_context), 0)

    def test_forward_context_rejects_mismatched_site(self) -> None:
        context = CallContext(is_backward=False)
        left = self._make_label(10, Parenthesis.LEFT_PAR)
        wrong_right = self._make_label(12, Parenthesis.RIGHT_PAR)

        self.assertTrue(context.add_and_check_context(left))
        self.assertFalse(context.add_and_check_context(wrong_right))
        self.assertEqual(len(context.simplified_context), 1)

    def test_backward_context_matches_right_then_left(self) -> None:
        context = CallContext(is_backward=True)
        right = self._make_label(21, Parenthesis.RIGHT_PAR)
        left = self._make_label(21, Parenthesis.LEFT_PAR)

        self.assertTrue(context.add_and_check_context(right))
        self.assertTrue(context.add_and_check_context(left))
        self.assertEqual(len(context.simplified_context), 0)


if __name__ == "__main__":
    unittest.main()
