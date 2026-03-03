import sys
import types
import unittest
from pathlib import Path


try:
    import tree_sitter  # noqa: F401
except ModuleNotFoundError:
    fake_tree_sitter = types.ModuleType("tree_sitter")

    class _DummyNodeType:
        pass

    class _DummyTreeType:
        pass

    class _DummyLanguage:
        def __init__(self, *args, **kwargs):
            pass

    class _DummyParser:
        def __init__(self, *args, **kwargs):
            pass

        def set_language(self, *args, **kwargs):
            return None

    fake_tree_sitter.Node = _DummyNodeType
    fake_tree_sitter.Tree = _DummyTreeType
    fake_tree_sitter.Language = _DummyLanguage
    fake_tree_sitter.Parser = _DummyParser
    sys.modules["tree_sitter"] = fake_tree_sitter


REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from memory.syntactic.function import Function  # noqa: E402
from tstool.analyzer.Java_TS_analyzer import Java_TSAnalyzer  # noqa: E402


class DummyNode:
    def __init__(self, node_type: str = "identifier"):
        self.type = node_type
        self.children = []
        self.start_byte = 0
        self.end_byte = 0

    def child_by_field_name(self, _name: str):
        return None


def make_function(
    function_id: int,
    function_name: str,
    param_types: list[str],
    *,
    class_name: str,
    file_path: str = "callee.java",
) -> Function:
    return Function(
        function_id=function_id,
        function_name=function_name,
        function_code="void f() {}",
        start_line_number=1,
        end_line_number=1,
        function_node=DummyNode("method_declaration"),
        file_path=file_path,
        class_name=class_name,
        param_types=param_types,
    )


class MockJavaAnalyzer(Java_TSAnalyzer):
    def __init__(self) -> None:
        self.code_in_files = {}
        self.fileContentBytes = {}
        self.classNameToFull = {}
        self.classFullToSimple = {}
        self.classFullToDeclaredSupers = {}
        self.classFullToSuper = {}
        self.classFullToSub = {}
        self._hierarchy_dirty = False
        self.methodKeyToId = {}
        self.function_env = {}

        self.mock_callsite_info = ("", "", [])
        self.mock_type_env = {}
        self.mock_arg_types = {}

    def _get_callsite_info(self, _node, _source_bytes):
        return self.mock_callsite_info

    def _build_type_env(self, _function):
        return dict(self.mock_type_env)

    def _infer_expression_type(self, expr_node, _source_bytes, _type_env):
        return self.mock_arg_types.get(id(expr_node), "")


class JavaCallResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = MockJavaAnalyzer()
        self.callsite_node = DummyNode("method_invocation")
        self.current_function = make_function(
            100,
            "caller",
            [],
            class_name="pkg.Caller",
            file_path="caller.java",
        )
        self.analyzer.code_in_files["caller.java"] = "class Caller {}"

    def test_dynamic_dispatch_expands_subclasses(self) -> None:
        self.analyzer.classNameToFull = {
            "Base": {"pkg.Base"},
            "Sub": {"pkg.Sub"},
            "Caller": {"pkg.Caller"},
        }
        self.analyzer.classFullToDeclaredSupers = {
            "pkg.Base": set(),
            "pkg.Sub": {"Base"},
            "pkg.Caller": set(),
        }
        self.analyzer._hierarchy_dirty = True

        self.analyzer.function_env = {
            1: make_function(1, "process", ["int"], class_name="pkg.Base"),
            2: make_function(2, "process", ["int"], class_name="pkg.Sub"),
        }
        self.analyzer.methodKeyToId = {
            ("pkg.Base", "process", 1): {1},
            ("pkg.Sub", "process", 1): {2},
        }

        arg_node = DummyNode("decimal_integer_literal")
        self.analyzer.mock_callsite_info = ("obj", "process", [arg_node])
        self.analyzer.mock_type_env = {"obj": "Base"}
        self.analyzer.mock_arg_types = {id(arg_node): "int"}

        callee_ids = self.analyzer.get_callee_function_ids_at_callsite(
            self.current_function, self.callsite_node
        )
        self.assertEqual(callee_ids, [1, 2])

    def test_static_receiver_does_not_expand_subclasses(self) -> None:
        self.analyzer.classNameToFull = {
            "Base": {"pkg.Base"},
            "Sub": {"pkg.Sub"},
            "Caller": {"pkg.Caller"},
        }
        self.analyzer.classFullToDeclaredSupers = {
            "pkg.Base": set(),
            "pkg.Sub": {"Base"},
            "pkg.Caller": set(),
        }
        self.analyzer._hierarchy_dirty = True

        self.analyzer.function_env = {
            1: make_function(1, "create", ["int"], class_name="pkg.Base"),
            2: make_function(2, "create", ["int"], class_name="pkg.Sub"),
        }
        self.analyzer.methodKeyToId = {
            ("pkg.Base", "create", 1): {1},
            ("pkg.Sub", "create", 1): {2},
        }

        arg_node = DummyNode("decimal_integer_literal")
        self.analyzer.mock_callsite_info = ("Base", "create", [arg_node])
        self.analyzer.mock_type_env = {}
        self.analyzer.mock_arg_types = {id(arg_node): "int"}

        callee_ids = self.analyzer.get_callee_function_ids_at_callsite(
            self.current_function, self.callsite_node
        )
        self.assertEqual(callee_ids, [1])

    def test_overload_is_filtered_by_argument_type(self) -> None:
        self.analyzer.classNameToFull = {
            "Svc": {"pkg.Svc"},
            "Caller": {"pkg.Caller"},
        }
        self.analyzer.classFullToDeclaredSupers = {
            "pkg.Svc": set(),
            "pkg.Caller": set(),
        }
        self.analyzer._hierarchy_dirty = True

        self.analyzer.function_env = {
            3: make_function(3, "put", ["int"], class_name="pkg.Svc"),
            4: make_function(4, "put", ["String"], class_name="pkg.Svc"),
        }
        self.analyzer.methodKeyToId = {("pkg.Svc", "put", 1): {3, 4}}

        arg_node = DummyNode("string_literal")
        self.analyzer.mock_callsite_info = ("svc", "put", [arg_node])
        self.analyzer.mock_type_env = {"svc": "Svc"}
        self.analyzer.mock_arg_types = {id(arg_node): "String"}

        callee_ids = self.analyzer.get_callee_function_ids_at_callsite(
            self.current_function, self.callsite_node
        )
        self.assertEqual(callee_ids, [4])


if __name__ == "__main__":
    unittest.main()
