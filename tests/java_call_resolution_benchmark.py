import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple


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
    param_types: List[str],
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


@dataclass
class Case:
    name: str
    receiver: str
    method: str
    receiver_type_env: Dict[str, str]
    arg_types: List[str]
    expected: Set[int]


def baseline_get_callee_ids(
    analyzer: MockJavaAnalyzer, current_function: Function, case: Case
) -> List[int]:
    receiver_expr = case.receiver
    type_env = case.receiver_type_env
    arg_count = len(case.arg_types)

    if not receiver_expr or receiver_expr == "this":
        candidate_classes = [current_function.class_name] if current_function.class_name else []
    else:
        base = receiver_expr
        if "." in base:
            parts = base.split(".")
            if parts[0] == "this" and len(parts) > 1:
                base = parts[1]
            else:
                base = parts[0]
        recv_type = analyzer._normalize_type_name(type_env.get(base, ""))
        candidate_classes = (
            list(analyzer.classNameToFull.get(recv_type, set()))
            if recv_type
            else []
        )
        if not candidate_classes:
            static_name = analyzer._normalize_type_name(base)
            candidate_classes = list(analyzer.classNameToFull.get(static_name, set()))

    if not candidate_classes and current_function.class_name:
        candidate_classes = [current_function.class_name]

    callee_ids: Set[int] = set()
    for class_full in candidate_classes:
        key = (class_full, case.method, arg_count)
        callee_ids.update(analyzer.methodKeyToId.get(key, set()))
    return sorted(callee_ids)


def collect_metrics(records: List[Tuple[Set[int], Set[int]]]) -> Dict[str, float]:
    tp = 0
    fp = 0
    fn = 0
    for expected, predicted in records:
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall > 0 else 0.0
    return {
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def build_benchmark() -> Tuple[MockJavaAnalyzer, Function, List[Case]]:
    analyzer = MockJavaAnalyzer()
    analyzer.code_in_files["caller.java"] = "class Caller {}"

    analyzer.classNameToFull = {
        "Caller": {"pkg.Caller"},
        "Base": {"pkg.Base"},
        "Sub": {"pkg.Sub"},
        "Svc": {"pkg.Svc"},
        "Iface": {"pkg.Iface"},
        "ImplA": {"pkg.ImplA"},
        "ImplB": {"pkg.ImplB"},
    }
    analyzer.classFullToDeclaredSupers = {
        "pkg.Caller": set(),
        "pkg.Base": set(),
        "pkg.Sub": {"Base"},
        "pkg.Svc": set(),
        "pkg.Iface": set(),
        "pkg.ImplA": {"Iface"},
        "pkg.ImplB": {"Iface"},
    }
    analyzer._hierarchy_dirty = True

    analyzer.function_env = {
        1: make_function(1, "process", ["int"], class_name="pkg.Base"),
        2: make_function(2, "process", ["int"], class_name="pkg.Sub"),
        3: make_function(3, "put", ["int"], class_name="pkg.Svc"),
        4: make_function(4, "put", ["String"], class_name="pkg.Svc"),
        5: make_function(5, "run", ["int"], class_name="pkg.Iface"),
        6: make_function(6, "run", ["int"], class_name="pkg.ImplA"),
        7: make_function(7, "run", ["int"], class_name="pkg.ImplB"),
    }
    analyzer.methodKeyToId = {
        ("pkg.Base", "process", 1): {1},
        ("pkg.Sub", "process", 1): {2},
        ("pkg.Svc", "put", 1): {3, 4},
        ("pkg.Iface", "run", 1): {5},
        ("pkg.ImplA", "run", 1): {6},
        ("pkg.ImplB", "run", 1): {7},
    }

    current_function = make_function(
        100,
        "caller",
        [],
        class_name="pkg.Caller",
        file_path="caller.java",
    )

    cases = [
        Case(
            name="dynamic_dispatch_base_ref",
            receiver="obj",
            method="process",
            receiver_type_env={"obj": "Base"},
            arg_types=["int"],
            expected={1, 2},
        ),
        Case(
            name="overload_string",
            receiver="svc",
            method="put",
            receiver_type_env={"svc": "Svc"},
            arg_types=["String"],
            expected={4},
        ),
        Case(
            name="overload_int",
            receiver="svc",
            method="put",
            receiver_type_env={"svc": "Svc"},
            arg_types=["int"],
            expected={3},
        ),
        Case(
            name="interface_dispatch",
            receiver="api",
            method="run",
            receiver_type_env={"api": "Iface"},
            arg_types=["int"],
            expected={5, 6, 7},
        ),
        Case(
            name="static_receiver",
            receiver="Base",
            method="process",
            receiver_type_env={},
            arg_types=["int"],
            expected={1},
        ),
    ]
    return analyzer, current_function, cases


def run_benchmark() -> Dict[str, object]:
    analyzer, current_function, cases = build_benchmark()
    callsite_node = DummyNode("method_invocation")

    before_records: List[Tuple[Set[int], Set[int]]] = []
    after_records: List[Tuple[Set[int], Set[int]]] = []
    case_results = []

    for case in cases:
        arg_nodes = [DummyNode("argument") for _ in case.arg_types]
        analyzer.mock_callsite_info = (case.receiver, case.method, arg_nodes)
        analyzer.mock_type_env = dict(case.receiver_type_env)
        analyzer.mock_arg_types = {
            id(arg_node): arg_type
            for arg_node, arg_type in zip(arg_nodes, case.arg_types)
        }

        before = set(baseline_get_callee_ids(analyzer, current_function, case))
        after = set(
            analyzer.get_callee_function_ids_at_callsite(current_function, callsite_node)
        )
        expected = set(case.expected)
        before_records.append((expected, before))
        after_records.append((expected, after))
        case_results.append(
            {
                "case": case.name,
                "expected": sorted(expected),
                "before": sorted(before),
                "after": sorted(after),
            }
        )

    return {
        "before": collect_metrics(before_records),
        "after": collect_metrics(after_records),
        "cases": case_results,
    }


if __name__ == "__main__":
    result = run_benchmark()
    print(json.dumps(result, indent=2, ensure_ascii=False))
