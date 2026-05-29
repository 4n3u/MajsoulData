from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROTO_TYPE_NAMES = {
    1: "double",
    2: "float",
    3: "int64",
    4: "uint64",
    5: "int32",
    6: "fixed64",
    7: "fixed32",
    8: "bool",
    9: "string",
    10: "group",
    11: "message",
    12: "bytes",
    13: "uint32",
    14: "enum",
    15: "sfixed32",
    16: "sfixed64",
    17: "sint32",
    18: "sint64",
}

LABEL_NAMES = {
    1: "optional",
    2: "required",
    3: "repeated",
}


@dataclass
class ProtoEnumValue:
    var_name: str
    name: str
    number: int
    index: int

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "number": self.number,
            "index": self.index,
        }


@dataclass
class ProtoEnum:
    var_name: str
    name: str
    full_name: str
    values: list[ProtoEnumValue] = field(default_factory=list)

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "values": [value.to_schema() for value in self.values],
        }


@dataclass
class ProtoField:
    var_name: str
    name: str
    full_name: str
    number: int
    label: int
    type_code: int
    raw_type_ref: str | None = None
    type_name: str | None = None

    @property
    def label_name(self) -> str:
        return LABEL_NAMES.get(self.label, f"label_{self.label}")

    @property
    def is_repeated(self) -> bool:
        return self.label == 3

    @property
    def proto_type(self) -> str:
        if self.type_code in (11, 14):
            return self.type_name or self._fallback_type_name()
        return PROTO_TYPE_NAMES.get(self.type_code, f"type_{self.type_code}")

    def _fallback_type_name(self) -> str:
        if not self.raw_type_ref:
            return PROTO_TYPE_NAMES.get(self.type_code, f"type_{self.type_code}")
        return self.raw_type_ref.rsplit(".", 1)[-1]

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "number": self.number,
            "label": self.label_name,
            "type": self.proto_type,
            "type_code": self.type_code,
            "raw_type_ref": self.raw_type_ref,
        }


@dataclass
class ProtoMessage:
    var_name: str
    name: str
    full_name: str
    fields: list[ProtoField] = field(default_factory=list)
    nested_messages: list["ProtoMessage"] = field(default_factory=list)
    nested_enums: list[ProtoEnum] = field(default_factory=list)

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "fields": [field.to_schema() for field in self.fields],
            "nested_enums": [enum.to_schema() for enum in self.nested_enums],
            "nested_messages": [message.to_schema() for message in self.nested_messages],
        }


@dataclass
class ProtoModule:
    name: str
    package: str
    imports: dict[str, str]
    messages: list[ProtoMessage]
    messages_by_var: dict[str, ProtoMessage]
    enums: list[ProtoEnum]
    enums_by_var: dict[str, ProtoEnum]

    @property
    def field_count(self) -> int:
        return sum(_message_field_count(message) for message in self.messages)

    @property
    def message_count(self) -> int:
        return sum(_message_count(message) for message in self.messages)

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "package": self.package,
            "proto": proto_filename(self.name),
            "imports": [
                {"alias": alias, "module": module_name, "proto": proto_filename(module_name)}
                for alias, module_name in sorted(self.imports.items())
            ],
            "enums": [enum.to_schema() for enum in self.enums],
            "messages": [message.to_schema() for message in self.messages],
        }


def _message_count(message: ProtoMessage) -> int:
    return 1 + sum(_message_count(nested) for nested in message.nested_messages)


def _message_field_count(message: ProtoMessage) -> int:
    return len(message.fields) + sum(
        _message_field_count(nested) for nested in message.nested_messages
    )


def proto_filename(module_name: str) -> str:
    stem = module_name.rsplit(".", 1)[-1]
    if stem.endswith("_pb"):
        stem = stem[: -len("_pb")]
    return f"{stem}.proto"


def parse_protocol_sources(sources: dict[str, str]) -> list[ProtoModule]:
    raw_modules = {
        module_name: _parse_raw_module(module_name, source)
        for module_name, source in sorted(sources.items())
    }
    modules = {
        module_name: _build_module(module_name, raw_module)
        for module_name, raw_module in raw_modules.items()
    }

    for module in modules.values():
        _resolve_field_types(module, modules)

    return [modules[module_name] for module_name in sorted(modules)]


def _parse_raw_module(module_name: str, source: str) -> dict[str, Any]:
    descriptor_vars = set(
        re.findall(r"\b([A-Za-z_]\w*)\s*=\s*[A-Za-z_]\w*\.Descriptor\(\)", source)
    )
    enum_vars = set(
        re.findall(r"\b([A-Za-z_]\w*)\s*=\s*[A-Za-z_]\w*\.EnumDescriptor\(\)", source)
    )
    enum_value_vars = set(
        re.findall(r"\b([A-Za-z_]\w*)\s*=\s*[A-Za-z_]\w*\.EnumValueDescriptor\(\)", source)
    )
    field_vars = set(
        re.findall(r"\b([A-Za-z_]\w*)\s*=\s*[A-Za-z_]\w*\.FieldDescriptor\(\)", source)
    )
    props: dict[str, dict[str, Any]] = {
        var_name: {} for var_name in descriptor_vars | enum_vars | enum_value_vars | field_vars
    }

    imports = _parse_imports(source)
    _parse_assignment_properties(source, props)

    return {
        "name": module_name,
        "imports": imports,
        "descriptor_vars": descriptor_vars,
        "enum_vars": enum_vars,
        "enum_value_vars": enum_value_vars,
        "field_vars": field_vars,
        "props": props,
    }


def _parse_imports(source: str) -> dict[str, str]:
    imports: dict[str, str] = {}
    patterns = [
        r"local\s+([A-Za-z_]\w*)\s*=\s*require\(\"(Protol\.[^\"]+)\"\)",
        r"local\s+([A-Za-z_]\w*)\s*=\s*require\('(Protol\.[^']+)'\)",
        r"local\s+([A-Za-z_]\w*)\s*=\s*require\"(Protol\.[^\"]+)\"",
        r"local\s+([A-Za-z_]\w*)\s*=\s*require'(Protol\.[^']+)'",
    ]
    for pattern in patterns:
        for alias, module_name in re.findall(pattern, source):
            imports[alias] = module_name
    return imports


def _parse_assignment_properties(source: str, props: dict[str, dict[str, Any]]) -> None:
    string_pattern = re.compile(
        r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*\"((?:\\.|[^\"\\])*)\""
    )
    for var_name, prop_name, value in string_pattern.findall(source):
        if var_name in props:
            props[var_name][prop_name] = _unescape_lua_string(value)

    number_pattern = re.compile(
        r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?)"
    )
    for var_name, prop_name, value in number_pattern.findall(source):
        if var_name in props:
            props[var_name][prop_name] = float(value) if "." in value else int(value)

    reference_pattern = re.compile(
        r"([A-Za-z_]\w*)\.(message_type|enum_type|containing_type)\s*=\s*"
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)"
    )
    for var_name, prop_name, value in reference_pattern.findall(source):
        if var_name in props:
            props[var_name][prop_name] = value

    list_pattern = re.compile(
        r"([A-Za-z_]\w*)\.(fields|nested_types|enum_types|extensions|values)\s*=\s*\{"
    )
    for match in list_pattern.finditer(source):
        var_name = match.group(1)
        if var_name not in props:
            continue
        prop_name = match.group(2)
        brace_index = match.end() - 1
        end = _find_balanced(source, brace_index)
        props[var_name][prop_name] = re.findall(
            r"\b[A-Za-z_]\w*\b",
            source[brace_index + 1 : end - 1],
        )

def _unescape_lua_string(value: str) -> str:
    escapes = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        '"': '"',
        "'": "'",
    }

    def replace(match: re.Match[str]) -> str:
        escaped = match.group(1)
        if escaped in escapes:
            return escapes[escaped]
        if escaped.isdigit():
            return chr(int(escaped, 10))
        return escaped

    return re.sub(r"\\(\d{1,3}|.)", replace, value)


def _find_balanced(source: str, start: int, opening: str = "{", closing: str = "}") -> int:
    depth = 0
    index = start
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in {'"', "'"}:
                quote = char
            elif char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return index + 1
        index += 1
    raise ValueError(f"Unbalanced {opening!r} at {start}")


def _build_module(module_name: str, raw_module: dict[str, Any]) -> ProtoModule:
    props = raw_module["props"]
    messages_by_var: dict[str, ProtoMessage] = {}
    enums_by_var: dict[str, ProtoEnum] = {}
    field_vars = raw_module["field_vars"]

    for var_name in sorted(raw_module["enum_vars"]):
        item = props.get(var_name, {})
        name = item.get("name")
        full_name = item.get("full_name")
        if not isinstance(name, str) or not isinstance(full_name, str):
            continue
        enum = ProtoEnum(var_name=var_name, name=name, full_name=full_name)
        for value_var in item.get("values", []):
            if value_var not in raw_module["enum_value_vars"]:
                continue
            value = _build_enum_value(value_var, props.get(value_var, {}))
            if value:
                enum.values.append(value)
        enum.values.sort(key=lambda value: value.index)
        enums_by_var[var_name] = enum

    for var_name in sorted(raw_module["descriptor_vars"]):
        item = props.get(var_name, {})
        name = item.get("name")
        full_name = item.get("full_name")
        if not isinstance(name, str) or not isinstance(full_name, str):
            continue
        messages_by_var[var_name] = ProtoMessage(
            var_name=var_name,
            name=name,
            full_name=full_name,
        )

    for var_name, message in messages_by_var.items():
        item = props.get(var_name, {})
        for field_var in item.get("fields", []):
            if field_var not in field_vars:
                continue
            field_item = props.get(field_var, {})
            field = _build_field(field_var, field_item)
            if field:
                message.fields.append(field)
        for nested_var in item.get("nested_types", []):
            nested = messages_by_var.get(nested_var)
            if nested:
                message.nested_messages.append(nested)
        for enum_var in item.get("enum_types", []):
            enum = enums_by_var.get(enum_var)
            if enum:
                message.nested_enums.append(enum)

    nested_vars = {
        nested.var_name
        for message in messages_by_var.values()
        for nested in message.nested_messages
    }
    nested_enum_vars = {
        enum.var_name
        for message in messages_by_var.values()
        for enum in message.nested_enums
    }
    top_level_messages = [
        message
        for var_name, message in sorted(messages_by_var.items())
        if var_name not in nested_vars
        and not isinstance(props.get(var_name, {}).get("containing_type"), str)
    ]
    top_level_enums = [
        enum
        for var_name, enum in sorted(enums_by_var.items())
        if var_name not in nested_enum_vars
    ]
    package = _module_package(
        top_level_messages or list(messages_by_var.values()),
        top_level_enums or list(enums_by_var.values()),
    )
    return ProtoModule(
        name=module_name,
        package=package,
        imports=raw_module["imports"],
        messages=top_level_messages,
        messages_by_var=messages_by_var,
        enums=top_level_enums,
        enums_by_var=enums_by_var,
    )


def _build_enum_value(var_name: str, item: dict[str, Any]) -> ProtoEnumValue | None:
    name = item.get("name")
    number = item.get("number")
    index = item.get("index")
    if not isinstance(name, str) or not isinstance(number, int) or not isinstance(index, int):
        return None
    return ProtoEnumValue(var_name=var_name, name=name, number=number, index=index)


def _build_field(var_name: str, item: dict[str, Any]) -> ProtoField | None:
    name = item.get("name")
    full_name = item.get("full_name")
    number = item.get("number")
    label = item.get("label", 1)
    type_code = item.get("type")
    if (
        not isinstance(name, str)
        or not isinstance(full_name, str)
        or not isinstance(number, int)
        or not isinstance(label, int)
        or not isinstance(type_code, int)
    ):
        return None
    return ProtoField(
        var_name=var_name,
        name=name,
        full_name=full_name,
        number=number,
        label=label,
        type_code=type_code,
        raw_type_ref=item.get("message_type") or item.get("enum_type"),
    )


def _module_package(messages: list[ProtoMessage], enums: list[ProtoEnum]) -> str:
    for message in messages:
        package = _package_from_full_name(message.full_name)
        if package:
            return package
    for enum in enums:
        package = _package_from_full_name(enum.full_name)
        if package:
            return package
    return ""


def _package_from_full_name(full_name: str) -> str:
    parts = full_name.lstrip(".").split(".")
    if len(parts) <= 1:
        return ""
    return ".".join(parts[:-1])


def _resolve_field_types(module: ProtoModule, modules: dict[str, ProtoModule]) -> None:
    for message in module.messages_by_var.values():
        for field in message.fields:
            if field.raw_type_ref:
                field.type_name = _resolve_type_ref(field.raw_type_ref, module, modules)


def _resolve_type_ref(
    raw_type_ref: str,
    module: ProtoModule,
    modules: dict[str, ProtoModule],
) -> str | None:
    if "." not in raw_type_ref:
        message = module.messages_by_var.get(raw_type_ref)
        if message:
            return message.full_name
        enum = module.enums_by_var.get(raw_type_ref)
        return enum.full_name if enum else None

    alias, var_name = raw_type_ref.split(".", 1)
    target_module_name = module.imports.get(alias)
    if not target_module_name:
        return None
    target_module = modules.get(target_module_name)
    if not target_module:
        return None
    message = target_module.messages_by_var.get(var_name)
    if message:
        return message.full_name
    enum = target_module.enums_by_var.get(var_name)
    return enum.full_name if enum else None


def render_proto_module(module: ProtoModule) -> str:
    lines = ['syntax = "proto3";', ""]
    if module.package:
        lines.extend([f"package {module.package};", ""])

    for imported_module in sorted(_used_imports(module)):
        lines.append(f'import "{proto_filename(imported_module)}";')
    if _used_imports(module):
        lines.append("")

    for index, enum in enumerate(module.enums):
        if index:
            lines.append("")
        lines.extend(_render_enum(enum, 0))
    if module.enums and module.messages:
        lines.append("")

    for index, message in enumerate(module.messages):
        if index:
            lines.append("")
        lines.extend(_render_message(message, 0))
    return "\n".join(lines).rstrip() + "\n"


def _used_imports(module: ProtoModule) -> set[str]:
    used: set[str] = set()
    for message in module.messages_by_var.values():
        for field in message.fields:
            if not field.raw_type_ref or "." not in field.raw_type_ref:
                continue
            alias = field.raw_type_ref.split(".", 1)[0]
            imported_module = module.imports.get(alias)
            if imported_module:
                used.add(imported_module)
    return used


def _render_enum(enum: ProtoEnum, indent: int) -> list[str]:
    prefix = " " * indent
    child_prefix = " " * (indent + 2)
    lines = [f"{prefix}enum {enum.name} {{"]
    numbers = [value.number for value in enum.values]
    if len(numbers) != len(set(numbers)):
        lines.append(f"{child_prefix}option allow_alias = true;")
    for value in sorted(enum.values, key=lambda item: item.index):
        lines.append(f"{child_prefix}{value.name} = {value.number};")
    lines.append(f"{prefix}}}")
    return lines


def _render_message(message: ProtoMessage, indent: int) -> list[str]:
    prefix = " " * indent
    child_prefix = " " * (indent + 2)
    lines = [f"{prefix}message {message.name} {{"]

    for index, enum in enumerate(message.nested_enums):
        if index or message.fields:
            lines.append("")
        lines.extend(_render_enum(enum, indent + 2))

    for index, nested in enumerate(message.nested_messages):
        if index or message.fields or message.nested_enums:
            lines.append("")
        lines.extend(_render_message(nested, indent + 2))

    if (message.nested_messages or message.nested_enums) and message.fields:
        lines.append("")

    for field in sorted(message.fields, key=lambda item: item.number):
        label = "repeated " if field.is_repeated else ""
        lines.append(
            f"{child_prefix}{label}{field.proto_type} {field.name} = {field.number};"
        )
    lines.append(f"{prefix}}}")
    return lines


def build_protocol_schema(modules: list[ProtoModule]) -> dict[str, Any]:
    return {
        "modules": [module.to_schema() for module in modules],
        "module_count": len(modules),
        "message_count": sum(module.message_count for module in modules),
        "enum_count": sum(len(module.enums) for module in modules),
        "field_count": sum(module.field_count for module in modules),
    }


def build_protocol_outputs(output_dir: Path, raw_dir: Path) -> dict[str, Any]:
    raw_protol_dir = raw_dir / "lua" / "LuaByte" / "Lua" / "Protol"
    raw_proto_config = raw_dir / "assets" / "MyAssets" / "docs" / "proto_config.bytes"
    protocol_dir = output_dir / "protocol"
    proto_dir = protocol_dir / "proto"

    if protocol_dir.exists():
        shutil.rmtree(protocol_dir)
    proto_dir.mkdir(parents=True, exist_ok=True)

    sources: dict[str, str] = {}
    if raw_protol_dir.exists():
        for lua_path in sorted(raw_protol_dir.glob("*.lua")):
            module_name = f"Protol.{lua_path.stem}"
            sources[module_name] = lua_path.read_text(
                encoding="utf-8",
                errors="surrogateescape",
            )

    modules = parse_protocol_sources(sources)
    for module in modules:
        (proto_dir / proto_filename(module.name)).write_text(
            render_proto_module(module),
            encoding="utf-8",
        )
    service_counts = build_service_outputs(protocol_dir, proto_dir, modules, raw_proto_config)

    schema = build_protocol_schema(modules)
    (protocol_dir / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    extra_proto_files = ["services.proto"] if service_counts["services"] else []
    doc_status = generate_protocol_markdown(protocol_dir, proto_dir, modules, extra_proto_files)
    return {
        "modules": len(modules),
        "messages": schema["message_count"],
        "enums": schema["enum_count"],
        "fields": schema["field_count"],
        "proto_files": len(modules),
        **service_counts,
        "doc": doc_status,
    }


def build_service_outputs(
    protocol_dir: Path,
    proto_dir: Path,
    modules: list[ProtoModule],
    raw_proto_config: Path,
) -> dict[str, int]:
    if not raw_proto_config.exists():
        return {"services": 0, "rpcs": 0, "unresolved_rpcs": 0}

    config = json.loads(raw_proto_config.read_text(encoding="utf-8", errors="replace"))
    services = normalize_services(config)
    type_index = build_message_type_index(modules)
    resolved_services, unresolved = resolve_services(services, type_index)

    (protocol_dir / "services.json").write_text(
        json.dumps(services, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if resolved_services:
        (proto_dir / "services.proto").write_text(
            render_services_proto(resolved_services),
            encoding="utf-8",
        )

    return {
        "services": len(services),
        "rpcs": sum(len(methods) for methods in services.values()),
        "unresolved_rpcs": len(unresolved),
    }


def normalize_services(config: dict[str, Any]) -> dict[str, dict[str, dict[str, str]]]:
    raw_services = config.get("service")
    if not isinstance(raw_services, dict):
        return {}

    services: dict[str, dict[str, dict[str, str]]] = {}
    for service_name, methods in sorted(raw_services.items()):
        if not isinstance(service_name, str) or not isinstance(methods, dict):
            continue
        normalized_methods: dict[str, dict[str, str]] = {}
        for method_name, spec in sorted(methods.items()):
            if not isinstance(method_name, str) or not isinstance(spec, dict):
                continue
            request = spec.get("request")
            response = spec.get("response")
            if isinstance(request, str) and isinstance(response, str):
                normalized_methods[method_name] = {
                    "request": request,
                    "response": response,
                }
        if normalized_methods:
            services[service_name] = normalized_methods
    return services


def build_message_type_index(modules: list[ProtoModule]) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    for module in modules:
        for message in module.messages_by_var.values():
            index.setdefault(message.name, (message.full_name, proto_filename(module.name)))
    return index


def resolve_services(
    services: dict[str, dict[str, dict[str, str]]],
    type_index: dict[str, tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    resolved_services: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    for service_name, methods in services.items():
        resolved_methods: list[dict[str, str]] = []
        imports: set[str] = set()
        for method_name, spec in methods.items():
            request = type_index.get(spec["request"])
            response = type_index.get(spec["response"])
            if not request or not response:
                unresolved.append(
                    {
                        "service": service_name,
                        "method": method_name,
                        "request": spec["request"],
                        "response": spec["response"],
                    }
                )
                continue
            imports.update((request[1], response[1]))
            resolved_methods.append(
                {
                    "name": method_name,
                    "request": request[0],
                    "response": response[0],
                }
            )
        if resolved_methods:
            resolved_services.append(
                {
                    "name": service_name,
                    "imports": sorted(imports),
                    "methods": resolved_methods,
                }
            )
    return resolved_services, unresolved


def render_services_proto(services: list[dict[str, Any]]) -> str:
    imports = sorted({import_name for service in services for import_name in service["imports"]})
    lines = ['syntax = "proto3";', "", "package lq;", ""]
    for import_name in imports:
        lines.append(f'import "{import_name}";')
    if imports:
        lines.append("")

    for service_index, service in enumerate(services):
        if service_index:
            lines.append("")
        lines.append(f"service {service['name']} {{")
        for method in service["methods"]:
            lines.append(
                f"  rpc {method['name']} ({method['request']}) returns ({method['response']});"
            )
        lines.append("}")
    return "\n".join(lines).rstrip() + "\n"


def generate_protocol_markdown(
    protocol_dir: Path,
    proto_dir: Path,
    modules: list[ProtoModule],
    extra_proto_files: list[str] | None = None,
) -> str:
    if not modules:
        return "skipped"
    if not shutil.which("protoc-gen-doc"):
        return "skipped"

    command = [
        "protoc",
        "--proto_path",
        str(proto_dir),
        "--doc_out",
        str(protocol_dir),
        "--doc_opt",
        "markdown,protocol.md",
        *[proto_filename(module.name) for module in modules],
        *(extra_proto_files or []),
    ]
    subprocess.run(command, check=True)
    strip_trailing_whitespace(protocol_dir / "protocol.md")
    return "protoc-gen-doc"


def strip_trailing_whitespace(path: Path) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
