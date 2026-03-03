import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import tree_sitter

from tstool.analyzer.TS_analyzer import *
from tstool.analyzer.Java_TS_analyzer import *
from ..dfbscan_extractor import *


class MLKEffectKind(Enum):
    ACQUIRE = "acquire"
    RELEASE = "release"
    TRANSFER = "transfer"


@dataclass(frozen=True)
class JavaMLKEffect:
    kind: MLKEffectKind
    resource_name: str
    line_number: int
    detail: str


@dataclass(frozen=True)
class JavaMLKCallEvent:
    line_number: int
    callee_ids: Tuple[int, ...]
    arg_roots: Tuple[str, ...]
    must_execute: bool


@dataclass(frozen=True)
class JavaMLKReturnBinding:
    target_name: str
    line_number: int
    callee_ids: Tuple[int, ...]
    must_execute: bool


@dataclass
class JavaMLKFunctionSummary:
    function: Function
    acquired_values: Dict[str, Value] = field(default_factory=dict)
    must_released_names: Set[str] = field(default_factory=set)
    may_released_names: Set[str] = field(default_factory=set)
    must_transferred_names: Set[str] = field(default_factory=set)
    may_transferred_names: Set[str] = field(default_factory=set)
    effects: List[JavaMLKEffect] = field(default_factory=list)

    param_name_to_index: Dict[str, int] = field(default_factory=dict)
    param_must_release_indices: Set[int] = field(default_factory=set)
    param_may_release_indices: Set[int] = field(default_factory=set)
    param_must_transfer_indices: Set[int] = field(default_factory=set)
    param_may_transfer_indices: Set[int] = field(default_factory=set)

    call_events: List[JavaMLKCallEvent] = field(default_factory=list)
    return_bindings: List[JavaMLKReturnBinding] = field(default_factory=list)

    returned_names: Set[str] = field(default_factory=set)
    local_safe_via_calls: Set[str] = field(default_factory=set)
    guard_branch_scopes: List[Tuple[int, int]] = field(default_factory=list)
    _sink_values_cache: Dict[str, Value] = field(default_factory=dict)

    def mark_acquired(self, resource_name: str, line_number: int) -> None:
        if not resource_name:
            return
        if resource_name not in self.acquired_values:
            self.acquired_values[resource_name] = Value(
                resource_name,
                line_number,
                ValueLabel.SRC,
                self.function.file_path,
            )
            self.effects.append(
                JavaMLKEffect(
                    MLKEffectKind.ACQUIRE,
                    resource_name,
                    line_number,
                    "Resource acquisition",
                )
            )

    @property
    def released_names(self) -> Set[str]:
        return self.must_released_names | self.may_released_names

    @property
    def transferred_names(self) -> Set[str]:
        return self.must_transferred_names | self.may_transferred_names

    def mark_released(
        self,
        resource_name: str,
        line_number: int,
        detail: str,
        must: bool = True,
    ) -> bool:
        if not resource_name:
            return False
        target_set = self.must_released_names if must else self.may_released_names
        is_changed = resource_name not in target_set
        target_set.add(resource_name)
        if must:
            self.may_released_names.discard(resource_name)
        if resource_name not in self._sink_values_cache:
            self._sink_values_cache[resource_name] = Value(
                resource_name,
                line_number,
                ValueLabel.SINK,
                self.function.file_path,
            )
        if is_changed:
            self.effects.append(
                JavaMLKEffect(MLKEffectKind.RELEASE, resource_name, line_number, detail)
            )
        index = self.param_name_to_index.get(resource_name)
        if index is not None:
            if must:
                self.param_must_release_indices.add(index)
                self.param_may_release_indices.discard(index)
            else:
                self.param_may_release_indices.add(index)
        return is_changed

    def mark_transferred(
        self,
        resource_name: str,
        line_number: int,
        detail: str,
        must: bool = True,
    ) -> bool:
        if not resource_name:
            return False
        target_set = self.must_transferred_names if must else self.may_transferred_names
        is_changed = resource_name not in target_set
        target_set.add(resource_name)
        if must:
            self.may_transferred_names.discard(resource_name)
        if is_changed:
            self.effects.append(
                JavaMLKEffect(MLKEffectKind.TRANSFER, resource_name, line_number, detail)
            )
        index = self.param_name_to_index.get(resource_name)
        if index is not None:
            if must:
                self.param_must_transfer_indices.add(index)
                self.param_may_transfer_indices.discard(index)
            else:
                self.param_may_transfer_indices.add(index)
        return is_changed

    def leak_sources(self) -> List[Value]:
        safe_names = (
            self.must_released_names
            | self.must_transferred_names
            | self.local_safe_via_calls
        )
        leaked = [
            value
            for name, value in self.acquired_values.items()
            if name not in safe_names
            and not self._is_balanced_in_same_guard_branch(name, value.line_number)
        ]
        leaked.sort(key=lambda x: x.line_number)
        return leaked

    def sink_values(self) -> List[Value]:
        sinks = list(self._sink_values_cache.values())
        sinks.sort(key=lambda x: x.line_number)
        return sinks

    def _is_balanced_in_same_guard_branch(
        self, resource_name: str, acquire_line: int
    ) -> bool:
        if not self.guard_branch_scopes:
            return False

        release_or_transfer_lines = {
            effect.line_number
            for effect in self.effects
            if effect.resource_name == resource_name
            and effect.kind in {MLKEffectKind.RELEASE, MLKEffectKind.TRANSFER}
            and effect.line_number >= acquire_line
        }
        if not release_or_transfer_lines:
            return False

        for branch_scope in self.guard_branch_scopes:
            if (
                not isinstance(branch_scope, tuple)
                or len(branch_scope) != 2
            ):
                continue
            branch_start, branch_end = branch_scope
            if branch_start <= 0 or branch_end <= 0:
                continue
            if not (branch_start <= acquire_line <= branch_end):
                continue
            if any(
                branch_start <= line_number <= branch_end
                for line_number in release_or_transfer_lines
            ):
                return True
        return False


_RULE_PATH = Path(__file__).resolve().parent / "java_resource_rules.json"


def _load_rules() -> dict:
    try:
        with open(_RULE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Fallback rules keep the extractor functional.
        return {
            "closeable_types": [],
            "close_methods": ["close"],
            "factory_methods": [],
            "collection_source_methods": ["add", "put"],
            "collection_sink_methods": ["remove", "clear"],
            "threadlocal_source_methods": ["set"],
            "threadlocal_sink_methods": ["remove"],
            "cache_source_methods": ["put"],
            "cache_sink_methods": ["invalidate", "remove", "clear"],
            "listener_source_methods": ["addListener", "register"],
            "listener_sink_methods": ["removeListener", "unregister"],
        }


def _node_text(node: tree_sitter.Node, source_code: str | bytes) -> str:
    if node is None:
        return ""
    data = source_code
    if isinstance(source_code, str):
        data = source_code.encode("utf-8")
    return data[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _line_number(node: tree_sitter.Node, source_code: str | bytes) -> int:
    data = source_code
    if isinstance(source_code, str):
        data = source_code.encode("utf-8")
    return data[: node.start_byte].count(b"\n") + 1


def _line_number_end(node: tree_sitter.Node, source_code: str | bytes) -> int:
    data = source_code
    if isinstance(source_code, str):
        data = source_code.encode("utf-8")
    return data[: node.end_byte].count(b"\n") + 1


def _normalize_type_name(type_name: str) -> str:
    return type_name.split(".")[-1].strip()

def _get_receiver_and_method(
    node: tree_sitter.Node, source_code: str | bytes
) -> Tuple[str, str]:
    # Prefer field-based access for tree-sitter Java
    obj_node = node.child_by_field_name("object")
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        receiver = _node_text(obj_node, source_code) if obj_node is not None else ""
        method = _node_text(name_node, source_code)
        return receiver, method

    # Fallback to legacy child scanning (for older grammars)
    children = node.children
    child_types = [child.type for child in children]
    if "." in child_types:
        dot_index = child_types.index(".")
        recv_node = children[dot_index - 1] if dot_index - 1 >= 0 else None
        method_node = (
            children[dot_index + 1] if dot_index + 1 < len(children) else None
        )
        return _node_text(recv_node, source_code), _node_text(method_node, source_code)
    if children:
        return "", _node_text(children[0], source_code)
    return "", ""

def _base_name(name: str) -> str:
    if not name:
        return ""
    return name.split(".")[-1]

def _extract_decl_type(decl_node: tree_sitter.Node, source_code: str | bytes) -> str:
    type_nodes = find_nodes_by_type(decl_node, "type_identifier")
    type_nodes += find_nodes_by_type(decl_node, "scoped_type_identifier")
    type_nodes += find_nodes_by_type(decl_node, "generic_type")
    type_nodes += find_nodes_by_type(decl_node, "type")
    if type_nodes:
        type_node = type_nodes[0]
        if type_node.type == "generic_type":
            inner = find_nodes_by_type(type_node, "type_identifier")
            if inner:
                type_node = inner[0]
        return _normalize_type_name(_node_text(type_node, source_code))
    return ""

def _looks_collection_type(type_name: str) -> bool:
    if not type_name:
        return False
    lower = type_name.lower()
    tokens = [
        "list",
        "set",
        "map",
        "queue",
        "deque",
        "stack",
        "collection",
        "vector",
        "table",
        "dict",
        "bag",
        "pool",
        "registry",
        "buffer",
    ]
    return any(tok in lower for tok in tokens)


def _looks_cache_type(type_name: str) -> bool:
    if not type_name:
        return False
    lower = type_name.lower()
    return "cache" in lower


def _looks_threadlocal_type(type_name: str) -> bool:
    if not type_name:
        return False
    return _normalize_type_name(type_name) == "ThreadLocal"


def _has_null_literal(node: tree_sitter.Node) -> bool:
    return len(find_nodes_by_type(node, "null_literal")) > 0


class Java_MLK_Extractor(DFBScanExtractor):
    """
    Extract sources/sinks for Java memory leak detection, covering five subtypes:
    - MLK_CLOSEABLE_UNCLOSED
    - MLK_THREADLOCAL_NOT_REMOVED
    - MLK_COLLECTION_RETENTION
    - MLK_CACHE_RETENTION
    - MLK_LISTENER_NOT_UNREGISTERED

    Out of scope in this extractor:
    - MLK_STATIC_CLASSLOADER_RETENTION
    """

    def __init__(self, ts_analyzer: TSAnalyzer):
        super().__init__(ts_analyzer)
        self.rules = _load_rules()
        self._field_types_by_file: Dict[str, Dict[str, str]] = {}
        self._summary_cache: Optional[Dict[int, JavaMLKFunctionSummary]] = None
        self._project_closeable_types: Set[str] = set()
        self._collect_field_info()
        self._project_closeable_types = self._collect_project_closeable_types()

    def _get_source_bytes(self, file_path: str) -> bytes:
        data = self.ts_analyzer.fileContentBytes.get(file_path)
        if data is None:
            data = self.ts_analyzer.code_in_files[file_path].encode("utf-8")
            self.ts_analyzer.fileContentBytes[file_path] = data
        return data

    def _collect_project_closeable_types(self) -> Set[str]:
        closeable_types: Set[str] = set()
        if not isinstance(self.ts_analyzer, Java_TSAnalyzer):
            return closeable_types

        for class_full, simple_name in self.ts_analyzer.classFullToSimple.items():
            for target_super in {"AutoCloseable", "Closeable", "Channel"}:
                if self._has_declared_supertype(class_full, target_super):
                    closeable_types.add(simple_name)
                    break
                if self.ts_analyzer._is_subtype(simple_name, target_super):
                    closeable_types.add(simple_name)
                    break
        return closeable_types

    def _has_declared_supertype(
        self, class_full: str, target_super: str
    ) -> bool:
        if not isinstance(self.ts_analyzer, Java_TSAnalyzer):
            return False
        target = _normalize_type_name(target_super)
        queue: List[str] = [class_full]
        visited: Set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for super_simple in self.ts_analyzer.classFullToDeclaredSupers.get(
                current, set()
            ):
                normalized = _normalize_type_name(super_simple)
                if normalized == target:
                    return True
                for super_full in self.ts_analyzer.classNameToFull.get(
                    normalized, set()
                ):
                    if super_full not in visited:
                        queue.append(super_full)
        return False

    def _looks_closeable_type_name(self, type_name: str) -> bool:
        normalized = _normalize_type_name(type_name)
        if not normalized:
            return False
        if normalized in set(self.rules.get("closeable_types", [])):
            return True
        return normalized in self._project_closeable_types

    def build_project_summaries(self) -> Dict[int, JavaMLKFunctionSummary]:
        if self._summary_cache is not None:
            return self._summary_cache

        summaries: Dict[int, JavaMLKFunctionSummary] = {}
        for function_id, function in self.ts_analyzer.function_env.items():
            if self._is_excluded_file(function.file_path):
                continue
            summaries[function_id] = self.build_function_summary(function)

        changed = True
        while changed:
            changed = False
            for summary in summaries.values():
                for binding in summary.return_bindings:
                    for callee_id in binding.callee_ids:
                        callee_summary = summaries.get(callee_id)
                        if callee_summary is None:
                            continue
                        if any(
                            returned_name in callee_summary.acquired_values
                            for returned_name in callee_summary.returned_names
                        ):
                            if binding.target_name not in summary.acquired_values:
                                summary.mark_acquired(
                                    binding.target_name, binding.line_number
                                )
                                changed = True

                for call_event in summary.call_events:
                    for callee_id in call_event.callee_ids:
                        callee_summary = summaries.get(callee_id)
                        if callee_summary is None:
                            continue
                        for arg_index, root_name in enumerate(call_event.arg_roots):
                            if not root_name:
                                continue
                            if arg_index in callee_summary.param_must_release_indices:
                                release_detail = (
                                    f"Resource released by callee "
                                    f"{callee_summary.function.function_name}"
                                )
                                if not call_event.must_execute:
                                    release_detail = (
                                        f"Resource may be released by callee "
                                        f"{callee_summary.function.function_name} "
                                        f"(conditional call site)"
                                    )
                                if summary.mark_released(
                                    root_name,
                                    call_event.line_number,
                                    release_detail,
                                    must=call_event.must_execute,
                                ):
                                    changed = True
                            elif arg_index in callee_summary.param_may_release_indices:
                                if summary.mark_released(
                                    root_name,
                                    call_event.line_number,
                                    (
                                        f"Resource may be released by callee "
                                        f"{callee_summary.function.function_name}"
                                    ),
                                    must=False,
                                ):
                                    changed = True
                            if arg_index in callee_summary.param_must_transfer_indices:
                                transfer_detail = (
                                    f"Resource ownership transferred by callee "
                                    f"{callee_summary.function.function_name}"
                                )
                                if not call_event.must_execute:
                                    transfer_detail = (
                                        f"Resource ownership may be transferred by callee "
                                        f"{callee_summary.function.function_name} "
                                        f"(conditional call site)"
                                    )
                                if summary.mark_transferred(
                                    root_name,
                                    call_event.line_number,
                                    transfer_detail,
                                    must=call_event.must_execute,
                                ):
                                    changed = True
                            elif arg_index in callee_summary.param_may_transfer_indices:
                                if summary.mark_transferred(
                                    root_name,
                                    call_event.line_number,
                                    (
                                        f"Resource ownership may be transferred by callee "
                                        f"{callee_summary.function.function_name}"
                                    ),
                                    must=False,
                                ):
                                    changed = True

        for summary in summaries.values():
            summary.local_safe_via_calls = (
                summary.must_released_names | summary.must_transferred_names
            ) & set(summary.acquired_values.keys())

        self._summary_cache = summaries
        return summaries

    def build_function_summary(self, function: Function) -> JavaMLKFunctionSummary:
        source_code = self._get_source_bytes(function.file_path)
        summary = JavaMLKFunctionSummary(function)
        summary.param_name_to_index = self._get_parameter_index_map(function, source_code)
        summary.guard_branch_scopes = self._collect_guard_branch_scopes(
            function, source_code
        )

        type_map = self._build_type_map(function, source_code)
        try_resources = self._collect_try_resources(function, source_code)
        bounded_caches = self._collect_bounded_caches(function, source_code)
        field_types = self._field_types_by_file.get(function.file_path, {})
        local_names = self._collect_local_names(function, source_code)
        alias_roots = {
            name: name for name in summary.param_name_to_index.keys()
        }

        nodes: List[tree_sitter.Node] = []
        nodes.extend(find_nodes_by_type(function.parse_tree_root_node, "variable_declarator"))
        nodes.extend(find_nodes_by_type(function.parse_tree_root_node, "assignment_expression"))
        nodes.extend(find_nodes_by_type(function.parse_tree_root_node, "method_invocation"))
        nodes.extend(find_nodes_by_type(function.parse_tree_root_node, "return_statement"))
        nodes = sorted(nodes, key=lambda node: (node.start_byte, node.end_byte))

        for node in nodes:
            if node.type == "variable_declarator":
                self._apply_variable_declarator(
                    function,
                    summary,
                    node,
                    source_code,
                    alias_roots,
                    local_names,
                    field_types,
                    type_map,
                    try_resources,
                    bounded_caches,
                )
            elif node.type == "assignment_expression":
                self._apply_assignment_expression(
                    function,
                    summary,
                    node,
                    source_code,
                    alias_roots,
                    local_names,
                    field_types,
                    type_map,
                    try_resources,
                    bounded_caches,
                )
            elif node.type == "method_invocation":
                self._apply_method_invocation(
                    function,
                    summary,
                    node,
                    source_code,
                    alias_roots,
                    field_types,
                    type_map,
                    bounded_caches,
                )
            elif node.type == "return_statement":
                self._apply_return_statement(
                    summary,
                    node,
                    source_code,
                    alias_roots,
                )
        return summary

    def _is_closeable_creation(
        self, node: tree_sitter.Node, source_code: str | bytes
    ) -> bool:
        factory_methods = set(self.rules.get("factory_methods", []))

        create_nodes = find_nodes_by_type(node, "object_creation_expression")
        create_nodes += find_nodes_by_type(node, "class_instance_creation_expression")
        for create_node in create_nodes:
            type_nodes = find_nodes_by_type(create_node, "type_identifier")
            type_nodes += find_nodes_by_type(create_node, "scoped_type_identifier")
            if not type_nodes:
                type_nodes = find_nodes_by_type(create_node, "identifier")
            if type_nodes:
                type_name = _normalize_type_name(
                    _node_text(type_nodes[0], source_code)
                )
                if self._looks_closeable_type_name(type_name):
                    return True

        for call_node in find_nodes_by_type(node, "method_invocation"):
            receiver, method = _get_receiver_and_method(call_node, source_code)
            full_name = f"{receiver}.{method}" if receiver else method
            if full_name in factory_methods or method in factory_methods:
                return True
        return False

    def _collect_field_info(self) -> None:
        for file_path, root in self.ts_analyzer.file_root_nodes.items():
            source_code = self._get_source_bytes(file_path)
            field_types: Dict[str, str] = {}
            for field_node in find_nodes_by_type(root, "field_declaration"):
                type_name = _extract_decl_type(field_node, source_code)
                for declarator in find_nodes_by_type(field_node, "variable_declarator"):
                    name_nodes = find_nodes_by_type(declarator, "identifier")
                    if not name_nodes:
                        continue
                    name = _node_text(name_nodes[0], source_code)
                    field_types[name] = type_name
            self._field_types_by_file[file_path] = field_types
        return

    def _build_type_map(
        self, function: Function, source_code: str | bytes
    ) -> Dict[str, str]:
        type_map: Dict[str, str] = {}
        type_map.update(self._field_types_by_file.get(function.file_path, {}))

        for param in find_nodes_by_type(
            function.parse_tree_root_node, "formal_parameter"
        ):
            type_name = _extract_decl_type(param, source_code)
            for ident in find_nodes_by_type(param, "identifier"):
                type_map[_node_text(ident, source_code)] = type_name

        for local_decl in find_nodes_by_type(
            function.parse_tree_root_node, "local_variable_declaration"
        ):
            type_name = _extract_decl_type(local_decl, source_code)
            for declarator in find_nodes_by_type(local_decl, "variable_declarator"):
                for ident in find_nodes_by_type(declarator, "identifier"):
                    type_map[_node_text(ident, source_code)] = type_name
        return type_map

    def _collect_bounded_caches(
        self, function: Function, source_code: str | bytes
    ) -> Set[str]:
        bounded: Set[str] = set()
        if not function.if_statements:
            return bounded
        # Map remove/clear calls by receiver and line.
        removal_calls: List[Tuple[str, int]] = []
        for call_node in find_nodes_by_type(
            function.parse_tree_root_node, "method_invocation"
        ):
            receiver, method = _get_receiver_and_method(call_node, source_code)
            if not receiver or not method:
                continue
            if method not in {"remove", "clear", "invalidate", "evict"}:
                continue
            removal_calls.append((_base_name(receiver), _line_number(call_node, source_code)))

        for (if_start, if_end), info in function.if_statements.items():
            condition_str = info[2] if len(info) > 2 else ""
            if "size" not in condition_str:
                continue
            if ">=" not in condition_str and ">" not in condition_str:
                continue
            for recv, line in removal_calls:
                if if_start <= line <= if_end:
                    if f"{recv}.size" in condition_str:
                        bounded.add(recv)
        return bounded

    def _collect_try_resources(
        self, function: Function, source_code: str | bytes
    ) -> Set[str]:
        # Prefer analyzer helper if available.
        if hasattr(self.ts_analyzer, "get_try_resources_in_function"):
            return self.ts_analyzer.get_try_resources_in_function(function)

        resources: Set[str] = set()
        spec_nodes = find_nodes_by_type(
            function.parse_tree_root_node, "resource_specification"
        )
        for spec in spec_nodes:
            res_nodes = find_nodes_by_type(spec, "resource")
            if not res_nodes:
                res_nodes = find_nodes_by_type(spec, "local_variable_declaration")
            for res in res_nodes:
                for ident in find_nodes_by_type(res, "identifier"):
                    resources.add(_node_text(ident, source_code))
        return resources

    def _get_parameter_index_map(
        self, function: Function, source_code: str | bytes
    ) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        params = sorted(
            find_nodes_by_type(function.parse_tree_root_node, "formal_parameter"),
            key=lambda node: node.start_byte,
        )
        for index, param in enumerate(params):
            name_node = param.child_by_field_name("name")
            if name_node is None:
                ident_nodes = find_nodes_by_type(param, "identifier")
                name_node = ident_nodes[0] if ident_nodes else None
            name = _node_text(name_node, source_code)
            if name:
                mapping[name] = index
        return mapping

    def _collect_local_names(
        self, function: Function, source_code: str | bytes
    ) -> Set[str]:
        local_names: Set[str] = set()
        for node in find_nodes_by_type(function.parse_tree_root_node, "formal_parameter"):
            for ident in find_nodes_by_type(node, "identifier"):
                local_names.add(_node_text(ident, source_code))
        for node in find_nodes_by_type(
            function.parse_tree_root_node, "variable_declarator"
        ):
            ident_nodes = find_nodes_by_type(node, "identifier")
            if ident_nodes:
                local_names.add(_node_text(ident_nodes[0], source_code))
        return local_names

    def _collect_switch_branch_scopes(
        self, function: Function, source_code: str | bytes
    ) -> List[Tuple[int, int]]:
        scopes: List[Tuple[int, int]] = []
        switch_nodes = find_nodes_by_type(function.parse_tree_root_node, "switch_expression")
        switch_nodes += find_nodes_by_type(function.parse_tree_root_node, "switch_statement")
        for switch_node in switch_nodes:
            branch_nodes, _ = self._get_switch_branch_nodes(switch_node)
            for branch in branch_nodes:
                start_line = _line_number(branch, source_code)
                end_line = _line_number_end(branch, source_code)
                if start_line <= 0 or end_line <= 0:
                    continue
                scopes.append((start_line, end_line))
        return scopes

    def _collect_guard_branch_scopes(
        self, function: Function, source_code: str | bytes
    ) -> List[Tuple[int, int]]:
        scopes: List[Tuple[int, int]] = []
        for info in function.if_statements.values():
            if len(info) < 5:
                continue
            for branch_scope in (info[3], info[4]):
                if (
                    not isinstance(branch_scope, tuple)
                    or len(branch_scope) != 2
                ):
                    continue
                start_line, end_line = branch_scope
                if start_line <= 0 or end_line <= 0:
                    continue
                scopes.append((start_line, end_line))
        scopes.extend(self._collect_switch_branch_scopes(function, source_code))
        scopes = sorted(set(scopes), key=lambda x: (x[0], x[1]))
        return scopes

    def _is_inside_parent_type(
        self, node: tree_sitter.Node, parent_types: Set[str]
    ) -> bool:
        current = getattr(node, "parent", None)
        while current is not None:
            if current.type in parent_types:
                return True
            current = getattr(current, "parent", None)
        return False

    def _get_if_branch_nodes(
        self, if_node: tree_sitter.Node
    ) -> Tuple[Optional[tree_sitter.Node], Optional[tree_sitter.Node]]:
        then_node = if_node.child_by_field_name("consequence")
        else_node = if_node.child_by_field_name("alternative")

        children = list(if_node.children)
        if then_node is None:
            seen_condition = False
            for child in children:
                if child.type == "parenthesized_expression":
                    seen_condition = True
                    continue
                if not seen_condition:
                    continue
                if child.type in {"if", "else", "(", ")"}:
                    continue
                then_node = child
                break

        if else_node is None:
            for index, child in enumerate(children):
                if child.type != "else":
                    continue
                for candidate in children[index + 1 :]:
                    if candidate.type == "else":
                        continue
                    else_node = candidate
                    break
                break
        return then_node, else_node

    def _find_enclosing_if_branch(
        self, node: tree_sitter.Node
    ) -> Optional[Tuple[tree_sitter.Node, tree_sitter.Node, tree_sitter.Node, str]]:
        current = node
        while current is not None:
            parent = getattr(current, "parent", None)
            if parent is None:
                break
            if parent.type == "if_statement":
                then_node, else_node = self._get_if_branch_nodes(parent)
                if then_node is not None and (
                    then_node.start_byte <= node.start_byte <= node.end_byte <= then_node.end_byte
                ):
                    if else_node is None:
                        return None
                    return parent, then_node, else_node, "then"
                if else_node is not None and (
                    else_node.start_byte <= node.start_byte <= node.end_byte <= else_node.end_byte
                ):
                    if then_node is None:
                        return None
                    return parent, then_node, else_node, "else"
            current = parent
        return None

    def _find_enclosing_switch_node(
        self, node: tree_sitter.Node
    ) -> Optional[tree_sitter.Node]:
        current = node
        while current is not None:
            if current.type in {"switch_expression", "switch_statement"}:
                return current
            current = getattr(current, "parent", None)
        return None

    def _find_enclosing_switch_branch(
        self, node: tree_sitter.Node
    ) -> Optional[Tuple[tree_sitter.Node, tree_sitter.Node]]:
        branch_node: Optional[tree_sitter.Node] = None
        current = node
        while current is not None:
            if (
                branch_node is None
                and current.type in {"switch_block_statement_group", "switch_rule"}
            ):
                branch_node = current
            if current.type in {"switch_expression", "switch_statement"}:
                if branch_node is not None:
                    return current, branch_node
                return None
            current = getattr(current, "parent", None)
        return None

    def _switch_branch_has_default(self, branch_node: tree_sitter.Node) -> bool:
        return len(find_nodes_by_type(branch_node, "default")) > 0

    def _is_label_only_switch_branch(self, branch_node: tree_sitter.Node) -> bool:
        if branch_node.type != "switch_block_statement_group":
            return False
        if self._switch_branch_has_default(branch_node):
            return False
        for child in branch_node.children:
            if child.type in {"switch_label", "case", "default", ":", ","}:
                continue
            # Any non-label statement means this is not a pure fallthrough label group.
            return False
        return True

    def _get_switch_branch_nodes(
        self, switch_node: tree_sitter.Node
    ) -> Tuple[List[tree_sitter.Node], bool]:
        branches: List[tree_sitter.Node] = []
        seen: Set[Tuple[int, int]] = set()
        for branch_type in ("switch_rule", "switch_block_statement_group"):
            for candidate in find_nodes_by_type(switch_node, branch_type):
                nearest_switch = self._find_enclosing_switch_node(candidate)
                if nearest_switch is None or not self._is_same_node(
                    nearest_switch, switch_node
                ):
                    continue
                key = (candidate.start_byte, candidate.end_byte)
                if key in seen:
                    continue
                seen.add(key)
                branches.append(candidate)
        branches.sort(key=lambda node: (node.start_byte, node.end_byte))
        has_default = any(self._switch_branch_has_default(branch) for branch in branches)
        return branches, has_default

    def _is_same_node(
        self, left: Optional[tree_sitter.Node], right: Optional[tree_sitter.Node]
    ) -> bool:
        if left is None or right is None:
            return False
        return (
            left.type == right.type
            and left.start_byte == right.start_byte
            and left.end_byte == right.end_byte
        )

    def _is_unconditional_within_branch(
        self, node: tree_sitter.Node, branch_root: tree_sitter.Node
    ) -> bool:
        if self._is_inside_parent_type(node, {"finally_clause"}):
            return True
        current = getattr(node, "parent", None)
        guarded_types = {
            "if_statement",
            "for_statement",
            "enhanced_for_statement",
            "while_statement",
            "do_statement",
            "catch_clause",
            "switch_expression",
            "switch_statement",
            "conditional_expression",
            "try_statement",
        }
        while current is not None and not self._is_same_node(current, branch_root):
            if current.type in guarded_types:
                return False
            current = getattr(current, "parent", None)
        return current is not None and self._is_same_node(current, branch_root)

    def _call_signature_by_text(
        self, call_node: tree_sitter.Node, source_code: str | bytes
    ) -> Tuple[str, str, Tuple[str, ...]]:
        receiver, method = _get_receiver_and_method(call_node, source_code)
        receiver_name = _base_name(receiver)
        arg_names = tuple(
            _base_name(_node_text(self._unwrap_expression(arg), source_code))
            for arg in self._get_call_argument_nodes(call_node)
        )
        return method, receiver_name, arg_names

    def _is_if_branch_covered_call(
        self, call_node: tree_sitter.Node, source_code: str | bytes
    ) -> bool:
        if call_node.type != "method_invocation":
            return False
        branch_info = self._find_enclosing_if_branch(call_node)
        if branch_info is None:
            return False
        _, then_node, else_node, branch_name = branch_info
        current_branch = then_node if branch_name == "then" else else_node
        other_branch = else_node if branch_name == "then" else then_node
        if not self._is_unconditional_within_branch(call_node, current_branch):
            return False
        target_sig = self._call_signature_by_text(call_node, source_code)
        for candidate in find_nodes_by_type(other_branch, "method_invocation"):
            if not self._is_unconditional_within_branch(candidate, other_branch):
                continue
            if self._call_signature_by_text(candidate, source_code) == target_sig:
                return True
        return False

    def _is_switch_branch_covered_call(
        self, call_node: tree_sitter.Node, source_code: str | bytes
    ) -> bool:
        if call_node.type != "method_invocation":
            return False
        branch_info = self._find_enclosing_switch_branch(call_node)
        if branch_info is None:
            return False
        switch_node, current_branch = branch_info
        if not self._is_unconditional_within_branch(call_node, current_branch):
            return False
        branch_nodes, has_default = self._get_switch_branch_nodes(switch_node)
        if len(branch_nodes) < 2 or not has_default:
            return False

        target_sig = self._call_signature_by_text(call_node, source_code)
        for branch in branch_nodes:
            if self._is_same_node(branch, current_branch):
                continue
            if self._is_label_only_switch_branch(branch):
                continue
            matched = False
            for candidate in find_nodes_by_type(branch, "method_invocation"):
                if not self._is_unconditional_within_branch(candidate, branch):
                    continue
                if self._call_signature_by_text(candidate, source_code) == target_sig:
                    matched = True
                    break
            if not matched:
                return False
        return True

    def _is_must_effect_node(
        self, node: tree_sitter.Node, source_code: Optional[str | bytes] = None
    ) -> bool:
        if self._is_inside_parent_type(node, {"finally_clause"}):
            return True
        if source_code is not None and self._is_if_branch_covered_call(
            node, source_code
        ):
            return True
        if source_code is not None and self._is_switch_branch_covered_call(
            node, source_code
        ):
            return True
        if self._is_inside_parent_type(
            node,
            {
                "if_statement",
                "for_statement",
                "enhanced_for_statement",
                "while_statement",
                "do_statement",
                "catch_clause",
                "switch_expression",
                "switch_statement",
                "conditional_expression",
                "try_statement",
            },
        ):
            return False
        return True

    def _unwrap_expression(self, node: tree_sitter.Node) -> tree_sitter.Node:
        current = node
        while current is not None and current.type in {"parenthesized_expression", "cast_expression"}:
            children = [child for child in current.children if child.type not in {"(", ")"}]
            if not children:
                break
            current = children[-1]
        return current

    def _resolve_root_name(
        self,
        node: tree_sitter.Node | None,
        source_code: str | bytes,
        alias_roots: Dict[str, str],
    ) -> str:
        if node is None:
            return ""
        node = self._unwrap_expression(node)
        text = _node_text(node, source_code).strip()
        if not text:
            return ""
        if node.type == "assignment_expression":
            _, rhs_node = self._get_assignment_sides(node)
            return self._resolve_root_name(rhs_node, source_code, alias_roots)
        base = _base_name(text)
        return alias_roots.get(base, base)

    def _get_initializer_node(
        self, declarator: tree_sitter.Node
    ) -> Optional[tree_sitter.Node]:
        value_node = declarator.child_by_field_name("value")
        if value_node is not None:
            return value_node
        children = declarator.children
        child_types = [child.type for child in children]
        if "=" in child_types:
            eq_index = child_types.index("=")
            if eq_index + 1 < len(children):
                return children[eq_index + 1]
        return None

    def _get_assignment_sides(
        self, assignment: tree_sitter.Node
    ) -> Tuple[Optional[tree_sitter.Node], Optional[tree_sitter.Node]]:
        left_node = assignment.child_by_field_name("left")
        right_node = assignment.child_by_field_name("right")
        if left_node is not None and right_node is not None:
            return left_node, right_node
        children = assignment.children
        child_types = [child.type for child in children]
        if "=" in child_types:
            eq_index = child_types.index("=")
            left_node = children[eq_index - 1] if eq_index - 1 >= 0 else None
            right_node = children[eq_index + 1] if eq_index + 1 < len(children) else None
        return left_node, right_node

    def _get_call_argument_nodes(
        self, call_node: tree_sitter.Node
    ) -> List[tree_sitter.Node]:
        argument_nodes: List[tree_sitter.Node] = []
        for child in call_node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type in {",", "(", ")"}:
                        continue
                    argument_nodes.append(arg)
                break
        return argument_nodes

    def _is_field_target(
        self,
        lhs_text: str,
        field_types: Dict[str, str],
        local_names: Set[str],
    ) -> bool:
        if not lhs_text:
            return False
        if lhs_text.startswith("this."):
            return True
        base = _base_name(lhs_text)
        return base in field_types and base not in local_names

    def _mark_assignment_root(
        self,
        lhs_name: str,
        rhs_node: Optional[tree_sitter.Node],
        source_code: str | bytes,
        alias_roots: Dict[str, str],
    ) -> None:
        if not lhs_name:
            return
        if rhs_node is None:
            alias_roots[lhs_name] = lhs_name
            return
        rhs_node = self._unwrap_expression(rhs_node)
        if rhs_node.type == "method_invocation":
            alias_roots[lhs_name] = lhs_name
            return
        alias_roots[lhs_name] = self._resolve_root_name(rhs_node, source_code, alias_roots)

    def _record_container_effects(
        self,
        summary: JavaMLKFunctionSummary,
        call_node: tree_sitter.Node,
        source_code: str | bytes,
        receiver_root: str,
        receiver_type: str,
        is_long_lived: bool,
        bounded_caches: Set[str],
    ) -> None:
        receiver_root = _base_name(receiver_root)
        if not receiver_root:
            return
        _, method = _get_receiver_and_method(call_node, source_code)
        line_number = _line_number(call_node, source_code)
        method_lc = method.lower()
        is_threadlocal = _looks_threadlocal_type(receiver_type)
        is_collection = _looks_collection_type(receiver_type)
        is_cache = _looks_cache_type(receiver_type)

        if (
            method in set(self.rules.get("threadlocal_source_methods", []))
            and is_threadlocal
            and is_long_lived
        ):
            if method_lc == "set" and _has_null_literal(call_node):
                return
            summary.mark_acquired(receiver_root, line_number)
            return

        if (
            method in set(self.rules.get("cache_source_methods", []))
            and is_cache
            and is_long_lived
        ):
            if receiver_root in bounded_caches:
                return
            summary.mark_acquired(receiver_root, line_number)
            return

        if (
            method in set(self.rules.get("listener_source_methods", []))
            and is_long_lived
        ):
            summary.mark_acquired(receiver_root, line_number)
            return

        if (
            method in set(self.rules.get("collection_source_methods", []))
            and is_collection
            and is_long_lived
        ):
            summary.mark_acquired(receiver_root, line_number)

    def _record_release_effects(
        self,
        summary: JavaMLKFunctionSummary,
        call_node: tree_sitter.Node,
        source_code: str | bytes,
        receiver_root: str,
        arg_roots: List[str],
        receiver_type: str,
        receiver_is_variable: bool,
    ) -> None:
        _, method = _get_receiver_and_method(call_node, source_code)
        line_number = _line_number(call_node, source_code)
        must_release = self._is_must_effect_node(call_node, source_code)
        close_methods = set(self.rules.get("close_methods", []))
        collection_sink_methods = set(self.rules.get("collection_sink_methods", []))
        cache_sink_methods = set(self.rules.get("cache_sink_methods", []))
        threadlocal_sink_methods = set(self.rules.get("threadlocal_sink_methods", []))
        listener_sink_methods = set(self.rules.get("listener_sink_methods", []))

        receiver_base = _base_name(receiver_root)
        is_threadlocal = _looks_threadlocal_type(receiver_type)
        is_collection = _looks_collection_type(receiver_type)
        is_cache = _looks_cache_type(receiver_type)

        if method in threadlocal_sink_methods and is_threadlocal:
            summary.mark_released(
                receiver_base, line_number, "ThreadLocal removal", must=must_release
            )
            return
        if method == "set" and is_threadlocal and _has_null_literal(call_node):
            summary.mark_released(
                receiver_base,
                line_number,
                "ThreadLocal reset to null",
                must=must_release,
            )
            return

        if method in close_methods or method.startswith("close"):
            if receiver_base and receiver_is_variable:
                summary.mark_released(
                    receiver_base,
                    line_number,
                    "Direct close/release",
                    must=must_release,
                )
                return
            if len(arg_roots) == 1:
                summary.mark_released(
                    arg_roots[0],
                    line_number,
                    "Utility close/release call",
                    must=must_release,
                )
                return

        if method in cache_sink_methods and is_cache:
            summary.mark_released(
                receiver_base, line_number, "Cache eviction", must=must_release
            )
            return
        if method in collection_sink_methods and is_collection:
            summary.mark_released(
                receiver_base, line_number, "Collection removal", must=must_release
            )
            return
        if method in listener_sink_methods:
            summary.mark_released(
                receiver_base, line_number, "Listener removal", must=must_release
            )

    def _apply_variable_declarator(
        self,
        function: Function,
        summary: JavaMLKFunctionSummary,
        node: tree_sitter.Node,
        source_code: str | bytes,
        alias_roots: Dict[str, str],
        local_names: Set[str],
        field_types: Dict[str, str],
        type_map: Dict[str, str],
        try_resources: Set[str],
        bounded_caches: Set[str],
    ) -> None:
        ident_nodes = find_nodes_by_type(node, "identifier")
        if not ident_nodes:
            return
        lhs_name = _node_text(ident_nodes[0], source_code)
        rhs_node = self._get_initializer_node(node)
        if lhs_name in try_resources:
            self._mark_assignment_root(lhs_name, rhs_node, source_code, alias_roots)
            return

        if rhs_node is not None and self._is_closeable_creation(rhs_node, source_code):
            summary.mark_acquired(lhs_name, _line_number(ident_nodes[0], source_code))
            alias_roots[lhs_name] = lhs_name
            return

        if rhs_node is not None and rhs_node.type == "method_invocation":
            callee_ids = tuple(
                self.ts_analyzer.get_callee_function_ids_at_callsite(function, rhs_node)
            )
            if callee_ids:
                summary.return_bindings.append(
                    JavaMLKReturnBinding(
                        lhs_name,
                        _line_number(ident_nodes[0], source_code),
                        callee_ids,
                        self._is_must_effect_node(rhs_node, source_code),
                    )
                )
            self._mark_assignment_root(lhs_name, rhs_node, source_code, alias_roots)
            return

        rhs_root = self._resolve_root_name(rhs_node, source_code, alias_roots)
        if rhs_root and self._is_field_target(lhs_name, field_types, local_names):
            must_transfer = self._is_must_effect_node(node)
            summary.mark_transferred(
                rhs_root,
                _line_number(ident_nodes[0], source_code),
                f"Assigned to field {lhs_name}",
                must=must_transfer,
            )
        self._mark_assignment_root(lhs_name, rhs_node, source_code, alias_roots)

    def _apply_assignment_expression(
        self,
        function: Function,
        summary: JavaMLKFunctionSummary,
        node: tree_sitter.Node,
        source_code: str | bytes,
        alias_roots: Dict[str, str],
        local_names: Set[str],
        field_types: Dict[str, str],
        type_map: Dict[str, str],
        try_resources: Set[str],
        bounded_caches: Set[str],
    ) -> None:
        left_node, right_node = self._get_assignment_sides(node)
        lhs_text = _node_text(left_node, source_code)
        lhs_name = _base_name(lhs_text)
        if lhs_name in try_resources:
            self._mark_assignment_root(lhs_name, right_node, source_code, alias_roots)
            return

        if right_node is not None and self._is_closeable_creation(right_node, source_code):
            line_number = _line_number(left_node, source_code) if left_node is not None else _line_number(node, source_code)
            summary.mark_acquired(lhs_name, line_number)
            alias_roots[lhs_name] = lhs_name
            return

        if right_node is not None and right_node.type == "method_invocation":
            callee_ids = tuple(
                self.ts_analyzer.get_callee_function_ids_at_callsite(function, right_node)
            )
            if callee_ids and lhs_name:
                summary.return_bindings.append(
                    JavaMLKReturnBinding(
                        lhs_name,
                        _line_number(left_node, source_code) if left_node is not None else _line_number(node, source_code),
                        callee_ids,
                        self._is_must_effect_node(right_node, source_code),
                    )
                )
            self._mark_assignment_root(lhs_name, right_node, source_code, alias_roots)
            return

        rhs_root = self._resolve_root_name(right_node, source_code, alias_roots)
        if rhs_root and self._is_field_target(lhs_text, field_types, local_names):
            must_transfer = self._is_must_effect_node(node)
            summary.mark_transferred(
                rhs_root,
                _line_number(left_node, source_code) if left_node is not None else _line_number(node, source_code),
                f"Assigned to field {lhs_text}",
                must=must_transfer,
            )
        self._mark_assignment_root(lhs_name, right_node, source_code, alias_roots)

    def _apply_method_invocation(
        self,
        function: Function,
        summary: JavaMLKFunctionSummary,
        node: tree_sitter.Node,
        source_code: str | bytes,
        alias_roots: Dict[str, str],
        field_types: Dict[str, str],
        type_map: Dict[str, str],
        bounded_caches: Set[str],
    ) -> None:
        receiver, _ = _get_receiver_and_method(node, source_code)
        receiver_root = self._resolve_root_name(
            node.child_by_field_name("object"), source_code, alias_roots
        )
        receiver_base = _base_name(receiver) if receiver else receiver_root
        arg_nodes = self._get_call_argument_nodes(node)
        arg_roots = [
            self._resolve_root_name(arg_node, source_code, alias_roots)
            for arg_node in arg_nodes
        ]
        receiver_type = type_map.get(_base_name(receiver_base), "")
        receiver_is_variable = _base_name(receiver_base) in type_map or _base_name(receiver_base) in alias_roots
        is_long_lived = _base_name(receiver_base) in field_types

        if receiver_base:
            self._record_container_effects(
                summary,
                node,
                source_code,
                receiver_base,
                receiver_type,
                is_long_lived,
                bounded_caches,
            )

        self._record_release_effects(
            summary,
            node,
            source_code,
            receiver_base,
            arg_roots,
            receiver_type,
            receiver_is_variable,
        )

        callee_ids = tuple(self.ts_analyzer.get_callee_function_ids_at_callsite(function, node))
        if callee_ids:
            summary.call_events.append(
                JavaMLKCallEvent(
                    _line_number(node, source_code),
                    callee_ids,
                    tuple(arg_roots),
                    self._is_must_effect_node(node, source_code),
                )
            )

    def _apply_return_statement(
        self,
        summary: JavaMLKFunctionSummary,
        node: tree_sitter.Node,
        source_code: str | bytes,
        alias_roots: Dict[str, str],
    ) -> None:
        line_number = _line_number(node, source_code)
        value_node = node.child_by_field_name("value")
        if value_node is None:
            children = [child for child in node.children if child.type not in {"return", ";"}]
            value_node = children[0] if children else None
        if value_node is not None and self._is_closeable_creation(value_node, source_code):
            synthetic_name = f"__ret_{line_number}"
            summary.mark_acquired(synthetic_name, line_number)
            summary.returned_names.add(synthetic_name)
            summary.mark_transferred(
                synthetic_name,
                line_number,
                "Returned newly created resource",
                must=True,
            )
            return
        root_name = self._resolve_root_name(value_node, source_code, alias_roots)
        if not root_name:
            return
        summary.returned_names.add(root_name)
        summary.mark_transferred(
            root_name,
            line_number,
            "Returned to caller",
            must=self._is_must_effect_node(node),
        )

    def extract_all(self) -> Tuple[List[Value], List[Value]]:
        summaries = self.build_project_summaries()
        source_map: Dict[str, Value] = {}
        sink_map: Dict[str, Value] = {}
        for function_id, function in self.ts_analyzer.function_env.items():
            if self._is_excluded_file(function.file_path):
                continue
            summary = summaries.get(function_id)
            if summary is None:
                continue
            for source in summary.acquired_values.values():
                source_map[str(source)] = source
            for sink in summary.sink_values():
                sink_map[str(sink)] = sink

        self.sources = sorted(
            source_map.values(),
            key=lambda value: (value.file, value.line_number, value.name),
        )
        self.sinks = sorted(
            sink_map.values(),
            key=lambda value: (value.file, value.line_number, value.name),
        )
        return self.sources, self.sinks

    def extract_sources(self, function: Function) -> List[Value]:
        summary = self.build_project_summaries().get(function.function_id)
        if summary is None:
            return []
        return sorted(
            summary.acquired_values.values(),
            key=lambda value: (value.file, value.line_number, value.name),
        )

    def extract_sinks(self, function: Function) -> List[Value]:
        summary = self.build_project_summaries().get(function.function_id)
        if summary is None:
            return []
        return summary.sink_values()
