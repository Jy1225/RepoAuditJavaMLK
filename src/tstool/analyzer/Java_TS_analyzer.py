import sys
import re
from os import path
from typing import List, Tuple, Dict, Set
import tree_sitter

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

from .TS_analyzer import *
from memory.syntactic.function import *
from memory.syntactic.value import *


class Java_TSAnalyzer(TSAnalyzer):
    """
    TSAnalyzer for Java source files using tree-sitter.
    Implements Java-specific parsing and analysis.
    """

    def extract_function_info(
        self, file_path: str, source_code: str, tree: tree_sitter.Tree
    ) -> None:
        """
        Parse the function information in a Java source file.
        Parse method declarations as function definitions.
        """
        source_bytes = source_code.encode("utf-8")
        if not hasattr(self, "classNameToFull"):
            self.classNameToFull: Dict[str, Set[str]] = {}
        if not hasattr(self, "classFullToSimple"):
            self.classFullToSimple: Dict[str, str] = {}
        if not hasattr(self, "classFullToDeclaredSupers"):
            self.classFullToDeclaredSupers: Dict[str, Set[str]] = {}
        if not hasattr(self, "classFullToSuper"):
            self.classFullToSuper: Dict[str, Set[str]] = {}
        if not hasattr(self, "classFullToSub"):
            self.classFullToSub: Dict[str, Set[str]] = {}
        if not hasattr(self, "_hierarchy_dirty"):
            self._hierarchy_dirty = False
        if not hasattr(self, "file_field_types"):
            self.file_field_types: Dict[str, Dict[str, str]] = {}

        package_name = self._get_package_name(tree.root_node, source_bytes)
        class_infos = self._collect_class_infos(
            tree.root_node, source_bytes, package_name
        )
        self.file_field_types[file_path] = self._collect_field_types(
            tree.root_node, source_bytes
        )

        all_function_definition_nodes = find_nodes_by_type(
            tree.root_node, "method_declaration"
        )
        for node in all_function_definition_nodes:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                declarators = find_nodes_by_type(node, "method_declarator")
                if declarators:
                    name_node = declarators[0].child_by_field_name("name")
                    if name_node is None:
                        ident_nodes = find_nodes_by_type(declarators[0], "identifier")
                        if ident_nodes:
                            name_node = ident_nodes[0]
            if name_node is None:
                ident_nodes = find_nodes_by_type(node, "identifier")
                if ident_nodes:
                    name_node = ident_nodes[0]
            if name_node is None:
                continue

            function_name = source_bytes[
                name_node.start_byte : name_node.end_byte
            ].decode("utf-8", errors="ignore")
            if function_name == "":
                continue

            start_line_number = source_bytes[: node.start_byte].count(b"\n") + 1
            end_line_number = source_bytes[: node.end_byte].count(b"\n") + 1
            function_id = len(self.functionRawDataDic) + 1
            class_full_name = self._get_enclosing_class_full(class_infos, node)
            param_types = self._extract_param_types(node, source_bytes)
            method_sig = self._build_method_sig(
                class_full_name, function_name, param_types
            )

            self.functionRawDataDic[function_id] = (
                function_name,
                start_line_number,
                end_line_number,
                node,
            )
            self.functionToFile[function_id] = file_path
            self.functionMeta[function_id] = {
                "package_name": package_name,
                "class_name": class_full_name,
                "param_types": param_types,
                "method_sig": method_sig,
            }
            method_key = (class_full_name, function_name, len(param_types))
            if method_key not in self.methodKeyToId:
                self.methodKeyToId[method_key] = set()
            self.methodKeyToId[method_key].add(function_id)

            if function_name not in self.functionNameToId:
                self.functionNameToId[function_name] = set()
            self.functionNameToId[function_name].add(function_id)
        return

    def _node_text(self, node: tree_sitter.Node | None, source_bytes: bytes) -> str:
        if node is None:
            return ""
        return source_bytes[node.start_byte : node.end_byte].decode(
            "utf-8", errors="ignore"
        )

    def _normalize_type_name(self, type_name: str) -> str:
        if not type_name:
            return ""
        type_name = re.sub(r"<.*>", "", type_name).strip()
        if " " in type_name:
            type_name = type_name.split()[-1]
        return type_name.split(".")[-1].strip()

    def _extract_type_text(
        self, node: tree_sitter.Node | None, source_bytes: bytes
    ) -> str:
        if node is None:
            return ""
        return self._node_text(node, source_bytes)

    def _extract_param_types(
        self, method_node: tree_sitter.Node, source_bytes: bytes
    ) -> List[str]:
        types: List[str] = []
        for param in find_nodes_by_type(method_node, "formal_parameter"):
            type_node = param.child_by_field_name("type")
            type_text = self._extract_type_text(type_node, source_bytes)
            type_text = type_text.replace("...", "[]")
            types.append(self._normalize_type_name(type_text))
        return types

    def _get_package_name(self, root: tree_sitter.Node, source_bytes: bytes) -> str:
        pkg_nodes = find_nodes_by_type(root, "package_declaration")
        if not pkg_nodes:
            return ""
        text = self._node_text(pkg_nodes[0], source_bytes)
        text = text.replace("package", "").replace(";", "").strip()
        return text

    def _collect_class_infos(
        self,
        root: tree_sitter.Node,
        source_bytes: bytes,
        package_name: str,
    ) -> List[Dict[str, object]]:
        class_infos: List[Dict[str, object]] = []
        for cls in find_nodes_by_type(root, "class_declaration"):
            name_node = cls.child_by_field_name("name")
            if name_node is None:
                ident_nodes = find_nodes_by_type(cls, "identifier")
                name_node = ident_nodes[0] if ident_nodes else None
            cls_name = self._node_text(name_node, source_bytes)
            if not cls_name:
                continue
            class_infos.append(
                {
                    "node": cls,
                    "start": cls.start_byte,
                    "end": cls.end_byte,
                    "name": cls_name,
                    "supers": self._extract_declared_supertypes(cls, source_bytes),
                    "full": "",
                }
            )

        for info in class_infos:
            parent = None
            for other in class_infos:
                if (
                    other["start"] < info["start"]
                    and other["end"] > info["end"]
                ):
                    if parent is None or (
                        other["end"] - other["start"]
                        < parent["end"] - parent["start"]
                    ):
                        parent = other
            info["parent"] = parent

        def resolve_full(info: Dict[str, object]) -> str:
            if info["full"]:
                return str(info["full"])
            parent = info.get("parent")
            if parent:
                parent_full = resolve_full(parent)
                info["full"] = f"{parent_full}.{info['name']}"
            else:
                info["full"] = info["name"]
            return str(info["full"])

        for info in class_infos:
            base_full = resolve_full(info)
            full_name = f"{package_name}.{base_full}" if package_name else base_full
            info["full"] = full_name
            simple = info["name"]
            if simple not in self.classNameToFull:
                self.classNameToFull[simple] = set()
            self.classNameToFull[simple].add(full_name)
            self.classFullToSimple[full_name] = str(simple)

        for info in class_infos:
            child_full = str(info["full"])
            self.classFullToDeclaredSupers[child_full] = set(info.get("supers", set()))

        self._hierarchy_dirty = True

        return class_infos

    def _extract_declared_supertypes(
        self, class_node: tree_sitter.Node, source_bytes: bytes
    ) -> Set[str]:
        header = self._node_text(class_node, source_bytes).split("{", 1)[0]
        supers: Set[str] = set()

        extends_match = re.search(r"\bextends\s+([A-Za-z_][\w$.]*)", header)
        if extends_match:
            supers.add(self._normalize_type_name(extends_match.group(1)))

        implements_match = re.search(
            r"\bimplements\s+([A-Za-z0-9_.$,\s]+)", header
        )
        if implements_match:
            for item in implements_match.group(1).split(","):
                normalized = self._normalize_type_name(item.strip())
                if normalized:
                    supers.add(normalized)
        return supers

    def _get_enclosing_class_full(
        self, class_infos: List[Dict[str, object]], method_node: tree_sitter.Node
    ) -> str:
        if not class_infos:
            return ""
        candidates = [
            info
            for info in class_infos
            if info["start"] <= method_node.start_byte <= info["end"]
        ]
        if not candidates:
            return ""
        best = min(candidates, key=lambda x: x["end"] - x["start"])
        return str(best["full"])

    def _collect_field_types(
        self, root: tree_sitter.Node, source_bytes: bytes
    ) -> Dict[str, str]:
        field_types: Dict[str, str] = {}
        for field_node in find_nodes_by_type(root, "field_declaration"):
            type_node = field_node.child_by_field_name("type")
            type_text = self._normalize_type_name(
                self._extract_type_text(type_node, source_bytes)
            )
            for declarator in find_nodes_by_type(field_node, "variable_declarator"):
                name_nodes = find_nodes_by_type(declarator, "identifier")
                if not name_nodes:
                    continue
                name = self._node_text(name_nodes[0], source_bytes)
                field_types[name] = type_text
        return field_types

    def _build_type_env(self, function: Function) -> Dict[str, str]:
        file_path = function.file_path
        source_bytes = self.fileContentBytes.get(file_path)
        if source_bytes is None:
            source_bytes = self.code_in_files[file_path].encode("utf-8")
            self.fileContentBytes[file_path] = source_bytes

        type_env = dict(self.file_field_types.get(file_path, {}))

        for param in find_nodes_by_type(
            function.parse_tree_root_node, "formal_parameter"
        ):
            type_node = param.child_by_field_name("type")
            name_node = param.child_by_field_name("name")
            if name_node is None:
                ident_nodes = find_nodes_by_type(param, "identifier")
                name_node = ident_nodes[0] if ident_nodes else None
            name = self._node_text(name_node, source_bytes)
            type_text = self._normalize_type_name(
                self._extract_type_text(type_node, source_bytes)
            )
            if name:
                type_env[name] = type_text

        for local_decl in find_nodes_by_type(
            function.parse_tree_root_node, "local_variable_declaration"
        ):
            type_node = local_decl.child_by_field_name("type")
            type_text = self._normalize_type_name(
                self._extract_type_text(type_node, source_bytes)
            )
            for declarator in find_nodes_by_type(local_decl, "variable_declarator"):
                name_nodes = find_nodes_by_type(declarator, "identifier")
                if not name_nodes:
                    continue
                name = self._node_text(name_nodes[0], source_bytes)
                if name:
                    type_env[name] = type_text

        return type_env

    def _get_callsite_info(
        self, node: tree_sitter.Node, source_bytes: bytes
    ) -> Tuple[str, str, List[tree_sitter.Node]]:
        obj_node = node.child_by_field_name("object")
        name_node = node.child_by_field_name("name")
        receiver = self._node_text(obj_node, source_bytes) if obj_node else ""
        method = self._node_text(name_node, source_bytes) if name_node else ""

        if not method:
            child_texts = [
                self._node_text(child, source_bytes) for child in node.children
            ]
            if "." in child_texts:
                method = child_texts[child_texts.index(".") + 1]
            elif child_texts:
                method = child_texts[0]

        arg_nodes: List[tree_sitter.Node] = []
        for child in node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type in {",", "(", ")"}:
                        continue
                    arg_nodes.append(arg)
                break
        return receiver, method, arg_nodes

    def _build_method_sig(
        self, class_full: str, method_name: str, param_types: List[str]
    ) -> str:
        if not class_full:
            return f"{method_name}({','.join(param_types)})"
        return f"{class_full}#{method_name}({','.join(param_types)})"

    def _resolve_candidate_classes(
        self,
        receiver_expr: str,
        type_env: Dict[str, str],
        current_function: Function,
    ) -> Tuple[List[str], bool]:
        if not receiver_expr or receiver_expr == "this":
            candidates = [current_function.class_name] if current_function.class_name else []
            return candidates, False

        base = receiver_expr
        if "." in base:
            parts = base.split(".")
            if parts[0] == "this" and len(parts) > 1:
                base = parts[1]
            else:
                base = parts[0]

        recv_type = type_env.get(base, "")
        recv_type = self._normalize_type_name(recv_type)
        candidates = list(self.classNameToFull.get(recv_type, [])) if recv_type else []

        if not candidates:
            static_name = self._normalize_type_name(base)
            candidates = list(self.classNameToFull.get(static_name, []))
            return candidates, len(candidates) > 0
        return candidates, False

    def _expand_cha_candidates(self, base_candidates: List[str]) -> List[str]:
        self._ensure_class_hierarchy()
        expanded: Set[str] = set(base_candidates)
        queue = list(base_candidates)
        while queue:
            parent = queue.pop(0)
            for child in self.classFullToSub.get(parent, set()):
                if child in expanded:
                    continue
                expanded.add(child)
                queue.append(child)
        return list(expanded)

    def _is_primitive_type(self, type_name: str) -> bool:
        return type_name in {
            "byte",
            "short",
            "int",
            "long",
            "float",
            "double",
            "char",
            "boolean",
        }

    def _boxed_to_primitive(self, type_name: str) -> str:
        boxed = {
            "Byte": "byte",
            "Short": "short",
            "Integer": "int",
            "Long": "long",
            "Float": "float",
            "Double": "double",
            "Character": "char",
            "Boolean": "boolean",
        }
        return boxed.get(type_name, type_name)

    def _is_subtype(self, child_simple: str, parent_simple: str) -> bool:
        self._ensure_class_hierarchy()
        if not child_simple or not parent_simple:
            return False
        if child_simple == parent_simple:
            return True

        child_fulls = self.classNameToFull.get(child_simple, set())
        parent_fulls = self.classNameToFull.get(parent_simple, set())
        if not child_fulls or not parent_fulls:
            return False

        for child_full in child_fulls:
            queue = [child_full]
            visited = set()
            while queue:
                cls = queue.pop(0)
                if cls in visited:
                    continue
                visited.add(cls)
                supers = self.classFullToSuper.get(cls, set())
                if supers & parent_fulls:
                    return True
                queue.extend(list(supers))
        return False

    def _ensure_class_hierarchy(self) -> None:
        if not getattr(self, "_hierarchy_dirty", False):
            return

        self.classFullToSuper = {}
        self.classFullToSub = {}
        for child_full, super_simples in self.classFullToDeclaredSupers.items():
            self.classFullToSuper.setdefault(child_full, set())
            for super_simple in super_simples:
                for super_full in self.classNameToFull.get(super_simple, set()):
                    self.classFullToSuper[child_full].add(super_full)
                    self.classFullToSub.setdefault(super_full, set()).add(child_full)
        self._hierarchy_dirty = False

    def _is_assignable_type(self, arg_type: str, param_type: str) -> bool:
        arg = self._normalize_type_name(arg_type)
        param = self._normalize_type_name(param_type)
        if not param or not arg:
            return True
        if arg == param:
            return True
        if arg == "null":
            return not self._is_primitive_type(param)

        arg_primitive = self._boxed_to_primitive(arg)
        param_primitive = self._boxed_to_primitive(param)
        if arg_primitive == param_primitive:
            return True

        widening = {
            "byte": {"short", "int", "long", "float", "double"},
            "short": {"int", "long", "float", "double"},
            "char": {"int", "long", "float", "double"},
            "int": {"long", "float", "double"},
            "long": {"float", "double"},
            "float": {"double"},
        }
        if (
            arg_primitive in widening
            and param_primitive in widening[arg_primitive]
        ):
            return True

        return self._is_subtype(arg, param)

    def _infer_expression_type(
        self,
        expr_node: tree_sitter.Node,
        source_bytes: bytes,
        type_env: Dict[str, str],
    ) -> str:
        node_type = expr_node.type
        expr_text = self._node_text(expr_node, source_bytes).strip()

        if node_type in {
            "decimal_integer_literal",
            "hex_integer_literal",
            "binary_integer_literal",
            "octal_integer_literal",
            "integer_literal",
        }:
            return "int"
        if node_type in {
            "decimal_floating_point_literal",
            "hex_floating_point_literal",
            "floating_point_literal",
        }:
            return "double"
        if node_type == "character_literal":
            return "char"
        if node_type in {"boolean_literal", "true", "false"}:
            return "boolean"
        if node_type == "string_literal":
            return "String"
        if node_type == "null_literal":
            return "null"

        if node_type in {
            "object_creation_expression",
            "class_instance_creation_expression",
        }:
            type_node = expr_node.child_by_field_name("type")
            if type_node is not None:
                return self._normalize_type_name(self._node_text(type_node, source_bytes))
            for candidate_type in [
                "type_identifier",
                "scoped_type_identifier",
                "generic_type",
            ]:
                candidates = find_nodes_by_type(expr_node, candidate_type)
                if candidates:
                    return self._normalize_type_name(
                        self._node_text(candidates[0], source_bytes)
                    )
            return ""

        if node_type == "cast_expression":
            type_node = expr_node.child_by_field_name("type")
            return self._normalize_type_name(self._node_text(type_node, source_bytes))

        if node_type == "parenthesized_expression":
            for child in expr_node.children:
                if child.type in {"(", ")"}:
                    continue
                return self._infer_expression_type(child, source_bytes, type_env)

        if node_type == "assignment_expression":
            value_node = expr_node.child_by_field_name("right")
            if value_node is not None:
                return self._infer_expression_type(value_node, source_bytes, type_env)

        if node_type == "identifier":
            return self._normalize_type_name(type_env.get(expr_text, ""))

        if node_type in {"field_access", "scoped_identifier"}:
            base = expr_text
            if "." in base:
                parts = base.split(".")
                if parts[0] == "this" and len(parts) > 1:
                    base = parts[1]
                else:
                    base = parts[0]
            return self._normalize_type_name(type_env.get(base, ""))

        if expr_text.startswith("this."):
            base = expr_text.split(".", 1)[1].split(".")[0]
            return self._normalize_type_name(type_env.get(base, ""))

        base = expr_text.split(".")[0] if "." in expr_text else expr_text
        return self._normalize_type_name(type_env.get(base, ""))

    def _is_type_compatible_with_method(
        self,
        arg_nodes: List[tree_sitter.Node],
        source_bytes: bytes,
        type_env: Dict[str, str],
        callee: Function,
    ) -> bool:
        if len(arg_nodes) != len(callee.param_types):
            return False
        for arg_node, param_type in zip(arg_nodes, callee.param_types):
            arg_type = self._infer_expression_type(arg_node, source_bytes, type_env)
            if not self._is_assignable_type(arg_type, param_type):
                return False
        return True

    def get_callee_function_ids_at_callsite(
        self, current_function: Function, call_site_node: tree_sitter.Node
    ) -> List[int]:
        file_path = current_function.file_path
        source_bytes = self.fileContentBytes.get(file_path)
        if source_bytes is None:
            source_bytes = self.code_in_files[file_path].encode("utf-8")
            self.fileContentBytes[file_path] = source_bytes

        receiver, method_name, arg_nodes = self._get_callsite_info(
            call_site_node, source_bytes
        )
        if not method_name:
            return []
        arg_count = len(arg_nodes)

        type_env = self._build_type_env(current_function)
        candidate_classes, is_static_receiver = self._resolve_candidate_classes(
            receiver, type_env, current_function
        )
        if not candidate_classes and current_function.class_name:
            candidate_classes = [current_function.class_name]
            is_static_receiver = False

        if not is_static_receiver:
            candidate_classes = self._expand_cha_candidates(candidate_classes)

        callee_ids: Set[int] = set()
        for class_full in candidate_classes:
            key = (class_full, method_name, arg_count)
            callee_ids.update(self.methodKeyToId.get(key, set()))

        if not callee_ids:
            return []

        filtered_callee_ids: List[int] = []
        for callee_id in sorted(callee_ids):
            callee = self.function_env.get(callee_id)
            if callee is None:
                continue
            if self._is_type_compatible_with_method(
                arg_nodes, source_bytes, type_env, callee
            ):
                filtered_callee_ids.append(callee_id)
        return filtered_callee_ids

    def extract_global_info(
        self, file_path: str, source_code: str, tree: tree_sitter.Tree
    ) -> None:
        """
        Parse the global (macro) information in a Java source file.
        Currently not implemented.
        """
        return

    def get_callee_name_at_call_site(
        self, node: tree_sitter.Node, source_code: str
    ) -> str:
        """
        Get the callee (method) name at the call site.
        Extract texts from children nodes.
        """
        source_bytes = source_code.encode("utf-8")
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return source_bytes[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="ignore"
            )
        child_texts = [
            source_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="ignore"
            )
            for child in node.children
        ]
        if "." in child_texts:
            function_name = child_texts[child_texts.index(".") + 1]
        else:
            function_name = child_texts[0] if child_texts else ""
        return function_name

    def get_callsites_by_callee_name(
        self, current_function: Function, callee_name: str
    ) -> List[tree_sitter.Node]:
        """
        Find call site nodes for the given callee name.
        """
        results = []
        file_content = self.code_in_files[current_function.file_path]
        call_site_nodes = find_nodes_by_type(
            current_function.parse_tree_root_node, "method_invocation"
        )
        for call_site in call_site_nodes:
            if (
                self.get_callee_name_at_call_site(call_site, file_content)
                == callee_name
            ):
                results.append(call_site)
        return results

    def get_arguments_at_callsite(
        self, current_function: Function, call_site_node: tree_sitter.Node
    ) -> Set[Value]:
        """
        Get arguments from a call site in a function.
        :param current_function: the function to be analyzed
        :param call_site_node: the node of the call site
        :return: the arguments
        """
        arguments: Set[Value] = set([])
        file_name = current_function.file_path
        source_code = self.code_in_files[file_name]
        source_bytes = source_code.encode("utf-8")
        for sub_node in call_site_node.children:
            if sub_node.type == "argument_list":
                arg_list = sub_node.children[1:-1]
                for element in arg_list:
                    if element.type != ",":
                        line_number = (
                            source_bytes[: element.start_byte].count(b"\n") + 1
                        )
                        arguments.add(
                            Value(
                                source_bytes[
                                    element.start_byte : element.end_byte
                                ].decode("utf-8", errors="ignore"),
                                line_number,
                                ValueLabel.ARG,
                                file_name,
                                len(arguments),
                            )
                        )
        return arguments

    def get_parameters_in_single_function(
        self, current_function: Function
    ) -> Set[Value]:
        """
        Find the parameters of a function.
        :param current_function: The function to be analyzed.
        :return: A set of parameters as values
        """
        if current_function.paras is not None:
            return current_function.paras
        current_function.paras = set([])
        file_content = self.code_in_files[current_function.file_path]
        file_bytes = file_content.encode("utf-8")
        parameters = find_nodes_by_type(
            current_function.parse_tree_root_node, "formal_parameter"
        )
        index = 0
        for parameter_node in parameters:
            for sub_node in find_nodes_by_type(parameter_node, "identifier"):
                parameter_name = file_bytes[
                    sub_node.start_byte : sub_node.end_byte
                ].decode("utf-8", errors="ignore")
                line_number = file_bytes[: sub_node.start_byte].count(b"\n") + 1
                current_function.paras.add(
                    Value(
                        parameter_name,
                        line_number,
                        ValueLabel.PARA,
                        current_function.file_path,
                        index,
                    )
                )
                index += 1
        return current_function.paras

    def get_return_values_in_single_function(
        self, current_function: Function
    ) -> Set[Value]:
        """
        Find the return values of a function.
        :param current_function: The function to be analyzed.
        :return: A set of return values
        """
        if current_function.retvals is not None:
            return current_function.retvals

        current_function.retvals = set([])
        file_content = self.code_in_files[current_function.file_path]
        file_bytes = file_content.encode("utf-8")
        retnodes = find_nodes_by_type(
            current_function.parse_tree_root_node, "return_statement"
        )
        for retnode in retnodes:
            line_number = file_bytes[: retnode.start_byte].count(b"\n") + 1
            restmts_str = file_bytes[
                retnode.start_byte : retnode.end_byte
            ].decode("utf-8", errors="ignore")
            returned_value = restmts_str.replace("return", "").strip()
            current_function.retvals.add(
                Value(
                    returned_value,
                    line_number,
                    ValueLabel.RET,
                    current_function.file_path,
                    0,
                )
            )
        return current_function.retvals

    def get_try_resources_in_function(self, current_function: Function) -> Set[str]:
        """
        Find resource variable names in try-with-resources blocks.
        Returns a set of variable identifiers declared in resource specifications.
        """
        file_content = self.code_in_files[current_function.file_path]
        file_bytes = file_content.encode("utf-8")
        resources: Set[str] = set()
        spec_nodes = find_nodes_by_type(
            current_function.parse_tree_root_node, "resource_specification"
        )
        for spec in spec_nodes:
            res_nodes = find_nodes_by_type(spec, "resource")
            if not res_nodes:
                res_nodes = find_nodes_by_type(spec, "local_variable_declaration")
            for res in res_nodes:
                for ident in find_nodes_by_type(res, "identifier"):
                    resources.add(
                        file_bytes[ident.start_byte : ident.end_byte].decode(
                            "utf-8", errors="ignore"
                        )
                    )
        return resources

    def get_if_statements(
        self, function: Function, source_code: str
    ) -> Dict[Tuple, Tuple]:
        """
        Find if-statements in the Java method.
        Returns a dictionary mapping a (start_line, end_line) tuple to the if-statement info.
        """
        if_statement_nodes = find_nodes_by_type(
            function.parse_tree_root_node, "if_statement"
        )
        source_bytes = source_code.encode("utf-8")
        if_statements = {}
        for if_node in if_statement_nodes:
            condition_str = ""
            condition_start_line = 0
            condition_end_line = 0
            true_branch_start_line = 0
            true_branch_end_line = 0
            else_branch_start_line = 0
            else_branch_end_line = 0

            block_num = 0
            for sub_target in if_node.children:
                if sub_target.type == "parenthesized_expression":
                    condition_start_line = (
                        source_bytes[: sub_target.start_byte].count(b"\n") + 1
                    )
                    condition_end_line = (
                        source_bytes[: sub_target.end_byte].count(b"\n") + 1
                    )
                    condition_str = source_bytes[
                        sub_target.start_byte : sub_target.end_byte
                    ].decode("utf-8", errors="ignore")
                if sub_target.type == "block":
                    lower_lines = []
                    upper_lines = []
                    for sub_sub in sub_target.children:
                        if sub_sub.type not in {"{", "}"}:
                            lower_lines.append(
                                source_bytes[: sub_sub.start_byte].count(b"\n") + 1
                            )
                            upper_lines.append(
                                source_bytes[: sub_sub.end_byte].count(b"\n") + 1
                            )
                    if lower_lines and upper_lines:
                        if block_num == 0:
                            true_branch_start_line = min(lower_lines)
                            true_branch_end_line = max(upper_lines)
                            block_num += 1
                        elif block_num == 1:
                            else_branch_start_line = min(lower_lines)
                            else_branch_end_line = max(upper_lines)
                            block_num += 1
                if sub_target.type == "expression_statement":
                    true_branch_start_line = (
                        source_bytes[: sub_target.start_byte].count(b"\n") + 1
                    )
                    true_branch_end_line = (
                        source_bytes[: sub_target.end_byte].count(b"\n") + 1
                    )

            if_statement_start_line = (
                source_bytes[: if_node.start_byte].count(b"\n") + 1
            )
            if_statement_end_line = (
                source_bytes[: if_node.end_byte].count(b"\n") + 1
            )
            line_scope = (if_statement_start_line, if_statement_end_line)
            info = (
                condition_start_line,
                condition_end_line,
                condition_str,
                (true_branch_start_line, true_branch_end_line),
                (else_branch_start_line, else_branch_end_line),
            )
            if_statements[line_scope] = info
        return if_statements

    def get_loop_statements(
        self, function: Function, source_code: str
    ) -> Dict[Tuple, Tuple]:
        """
        Find loop statements in the Java method.
        Returns a dictionary mapping (start_line, end_line) to loop statement information.
        """
        loop_statements = {}
        source_bytes = source_code.encode("utf-8")
        root_node = function.parse_tree_root_node
        for_statement_nodes = find_nodes_by_type(root_node, "for_statement")
        for_statement_nodes.extend(
            find_nodes_by_type(root_node, "enhanced_for_statement")
        )
        while_statement_nodes = find_nodes_by_type(root_node, "while_statement")

        for loop_node in for_statement_nodes:
            loop_start_line = source_bytes[: loop_node.start_byte].count(b"\n") + 1
            loop_end_line = source_bytes[: loop_node.end_byte].count(b"\n") + 1

            header_line_start = 0
            header_line_end = 0
            header_str = ""
            loop_body_start_line = 0
            loop_body_end_line = 0

            header_start_byte = 0
            header_end_byte = 0

            for child in loop_node.children:
                if child.type == "(":
                    header_line_start = (
                        source_bytes[: child.start_byte].count(b"\n") + 1
                    )
                    header_start_byte = child.end_byte
                if child.type == ")":
                    header_line_end = (
                        source_bytes[: child.end_byte].count(b"\n") + 1
                    )
                    header_end_byte = child.start_byte
                    header_str = source_bytes[
                        header_start_byte:header_end_byte
                    ].decode("utf-8", errors="ignore")
                if child.type == "block":
                    lower_lines = []
                    upper_lines = []
                    for sub in child.children:
                        if sub.type not in {"{", "}"}:
                            lower_lines.append(
                                source_bytes[: sub.start_byte].count(b"\n") + 1
                            )
                            upper_lines.append(
                                source_bytes[: sub.end_byte].count(b"\n") + 1
                            )
                    if lower_lines and upper_lines:
                        loop_body_start_line = min(lower_lines)
                        loop_body_end_line = max(upper_lines)
                if child.type == "expression_statement":
                    loop_body_start_line = (
                        source_bytes[: child.start_byte].count(b"\n") + 1
                    )
                    loop_body_end_line = (
                        source_bytes[: child.end_byte].count(b"\n") + 1
                    )
            loop_statements[(loop_start_line, loop_end_line)] = (
                header_line_start,
                header_line_end,
                header_str,
                loop_body_start_line,
                loop_body_end_line,
            )

        for loop_node in while_statement_nodes:
            loop_start_line = source_bytes[: loop_node.start_byte].count(b"\n") + 1
            loop_end_line = source_bytes[: loop_node.end_byte].count(b"\n") + 1

            header_line_start = 0
            header_line_end = 0
            header_str = ""
            loop_body_start_line = 0
            loop_body_end_line = 0

            for child in loop_node.children:
                if child.type == "parenthesized_expression":
                    header_line_start = (
                        source_bytes[: child.start_byte].count(b"\n") + 1
                    )
                    header_line_end = (
                        source_bytes[: child.end_byte].count(b"\n") + 1
                    )
                    header_str = source_bytes[
                        child.start_byte : child.end_byte
                    ].decode("utf-8", errors="ignore")
                if child.type == "block":
                    lower_lines = []
                    upper_lines = []
                    for sub in child.children:
                        if sub.type not in {"{", "}"}:
                            lower_lines.append(
                                source_bytes[: sub.start_byte].count(b"\n") + 1
                            )
                            upper_lines.append(
                                source_bytes[: sub.end_byte].count(b"\n") + 1
                            )
                    if lower_lines and upper_lines:
                        loop_body_start_line = min(lower_lines)
                        loop_body_end_line = max(upper_lines)
            loop_statements[(loop_start_line, loop_end_line)] = (
                header_line_start,
                header_line_end,
                header_str,
                loop_body_start_line,
                loop_body_end_line,
            )
        return loop_statements
