from pathlib import Path
from typing import Callable, List, Set, Union

from codegen import convert_camel_case_to_snake_case, format_code
from codegen import get_code_intent as _
from codegen import get_sync_async_keywords, join_code, sort_dict_by_key, write_code
from codegen.models.generator import (
    get_data_model_name,
    get_options_model_name,
    get_params_model_name,
    get_response_model_name,
)
from codegen.namespaces.builder import MethodInfo, RecordInfo, build_namespaces
from lexicon.models import LexDefinitionType, LexObject, LexRef, LexXrpcProcedure

_NAMESPACES_OUTPUT_DIR = Path(__file__).parent.parent.parent.joinpath('xrpc_client', 'namespaces')
_NAMESPACES_CLIENT_FILE_PATH = _NAMESPACES_OUTPUT_DIR.joinpath('client', 'raw.py')

_NAMESPACES_SYNC_FILENAME = 'sync_ns.py'
_NAMESPACES_ASYNC_FILENAME = 'async_ns.py'

_NAMESPACE_SUFFIX = 'Namespace'
_RECORD_SUFFIX = 'RecordNamespace'


def get_namespace_name(path_part: str) -> str:
    return f'{path_part.capitalize()}{_NAMESPACE_SUFFIX}'


def get_record_name(path_part: str) -> str:
    return f'{path_part.capitalize()}{_RECORD_SUFFIX}'


def _get_namespace_imports() -> str:
    lines = [
        # isort formatted
        'from dataclasses import dataclass',
        'from typing import Optional, Union',
        '',
        'from xrpc_client import models',
        'from xrpc_client.models import get_or_create_model, get_response_model',
        'from xrpc_client.namespaces.base import DefaultNamespace, NamespaceBase',
    ]

    return join_code(lines)


def _get_namespace_class_def(name: str) -> str:
    lines = ['@dataclass', f'class {get_namespace_name(name)}(NamespaceBase):']

    return join_code(lines)


def _get_sub_namespaces_block(sub_namespaces: dict) -> str:
    lines = []

    sub_namespaces = sort_dict_by_key(sub_namespaces)
    for sub_namespace in sub_namespaces.keys():
        lines.append(f"{_(1)}{sub_namespace}: '{get_namespace_name(sub_namespace)}' = DefaultNamespace()")

    return join_code(lines)


def _get_post_init_method(sub_namespaces: dict) -> str:
    lines = [f'{_(1)}def __post_init__(self):']

    sub_namespaces = sort_dict_by_key(sub_namespaces)
    for sub_namespace in sub_namespaces.keys():
        lines.append(f'{_(2)}self.{sub_namespace} = {get_namespace_name(sub_namespace)}(self._client)')

    # TODO(MarshalX): add support for records

    return join_code(lines)


def _get_namespace_method_body(method_info: MethodInfo, *, sync: bool) -> str:
    d, c = get_sync_async_keywords(sync=sync)

    lines = []

    presented_args = _get_namespace_method_signature_args_names(method_info)
    presented_args.remove('self')

    def _override_arg_line(name: str, model_name: str) -> str:
        return f'{_(2)}{name} = get_or_create_model({name}, models.{model_name})'

    invoke_args = [f"'{method_info.nsid}'"]

    if 'params' in presented_args:
        invoke_args.append('params=params')
        lines.append(_override_arg_line('params', get_params_model_name(method_info.name)))
    elif 'data_schema' in presented_args:
        invoke_args.append('data=data')
        lines.append(_override_arg_line('data', get_data_model_name(method_info.name)))
    elif 'data_alias' in presented_args:
        invoke_args.append('data=data')
    elif 'options' in presented_args:
        invoke_args.append('options=options')
        lines.append(_override_arg_line('options', get_options_model_name(method_info.name)))

    invoke_args_str = ', '.join(invoke_args)

    method_name = 'invoke_query'
    if isinstance(method_info.definition, LexXrpcProcedure):
        method_name = 'invoke_procedure'

    lines.append(f"{_(2)}response = {c}self._client.{method_name}({invoke_args_str})")

    return_type = _get_namespace_method_return_type(method_info)
    lines.append(f"{_(2)}return get_response_model(response, {return_type})")

    return join_code(lines)


def _get_namespace_method_signature_arg(
    name: str, method_name: str, get_model_name: Callable, *, optional: bool, alias: bool = False
) -> str:
    model_name = get_model_name(method_name)

    if alias:
        return f"{name}: 'models.{model_name}'"

    default_value = ''
    type_hint = f"Union[dict, 'models.{model_name}']"
    if optional:
        type_hint = f'Optional[{type_hint}]'
        default_value = ' = None'

    return f'{name}: {type_hint}{default_value}'


def _get_namespace_method_signature_args_names(method_info: MethodInfo) -> Set[str]:
    args = {'self'}
    if method_info.definition.parameters:
        args.add('params')
    if method_info.definition.type is LexDefinitionType.PROCEDURE and method_info.definition.input:
        if method_info.definition.input.schema:
            args.add('data_schema')
        else:
            args.add('data_alias')

        # TODO(MarshalX): when be ready
        # args.append('options') # or **kwargs

    return args


def _get_namespace_method_signature_args(method_info: MethodInfo) -> str:
    args = ['self']
    optional_args = []

    def _add_arg(arg_def: str, *, optional: bool) -> None:
        if optional:
            optional_args.append(arg_def)
        else:
            args.append(arg_def)

    def is_optional_arg(lex_obj) -> bool:
        return lex_obj.required is None or len(lex_obj.required) == 0

    name = method_info.name

    if method_info.definition.parameters:
        params = method_info.definition.parameters
        is_optional = is_optional_arg(params)

        arg = _get_namespace_method_signature_arg('params', name, get_params_model_name, optional=is_optional)
        _add_arg(arg, optional=is_optional)

    if method_info.definition.type is LexDefinitionType.PROCEDURE and method_info.definition.input:
        schema = method_info.definition.input.schema
        if schema:
            is_optional = is_optional_arg(schema)

            if schema and isinstance(schema, LexObject):
                arg = _get_namespace_method_signature_arg('data', name, get_data_model_name, optional=is_optional)
                _add_arg(arg, optional=is_optional)
            else:
                raise ValueError(f'Bad type {type(schema)}')  # LexRefVariant
        else:
            arg = _get_namespace_method_signature_arg('data', name, get_data_model_name, optional=False, alias=True)
            _add_arg(arg, optional=False)

        # TODO(MarshalX): Options like encoding. Maybe without model? Simple kwargs for .invoke()

    args.extend(optional_args)
    return ', '.join(args)


def _get_namespace_method_return_type(method_info: MethodInfo) -> str:
    model_name_suffix = ''
    if method_info.definition.output and isinstance(method_info.definition.output.schema, LexRef):
        # fix collisions with type aliases
        # example of collisions: com.atproto.admin.getRepo, com.atproto.sync.getRepo
        # could be solved by separating models into different folders using segments of NSID
        model_name_suffix = 'Ref'

    return_type = 'int'  # return status code of response
    if method_info.definition.output:
        # example of methods without response: app.bsky.graph.muteActor, app.bsky.graph.muteActor
        return_type = f'models.{get_response_model_name(method_info.name)}{model_name_suffix}'

    return return_type


def _get_namespace_method_signature(method_info: MethodInfo, *, sync: bool) -> str:
    d, c = get_sync_async_keywords(sync=sync)

    name = convert_camel_case_to_snake_case(method_info.name)
    args = _get_namespace_method_signature_args(method_info)
    return_type = _get_namespace_method_return_type(method_info)

    return f'{_(1)}{d}def {name}({args}) -> {return_type}:'


def _get_namespace_methods_block(methods_info: List[MethodInfo], sync: bool) -> str:
    lines = []

    methods_info.sort(key=lambda e: e.name)
    for method_info in methods_info:
        lines.append(_get_namespace_method_signature(method_info, sync=sync))
        lines.append(_get_namespace_method_body(method_info, sync=sync))

    return join_code(lines)


def _get_namespace_records_block(records_info: List[RecordInfo]) -> str:
    lines = []

    records_info.sort(key=lambda e: e.name)
    for record_info in records_info:
        lines.append(f"{_(1)}{record_info.name}: '{get_record_name(record_info.name)}' = DefaultNamespace()")

    return join_code(lines)


def _generate_namespace_in_output(namespace_tree: Union[dict, list], output: List[str], *, sync: bool) -> None:
    for node_name, sub_node in namespace_tree.items():
        if isinstance(sub_node, dict):
            output.append(_get_namespace_class_def(node_name))
            output.append(_get_sub_namespaces_block(sub_node))
            output.append(_get_post_init_method(sub_node))

            _generate_namespace_in_output(sub_node, output, sync=sync)

        if isinstance(sub_node, list):
            output.append(_get_namespace_class_def(node_name))

            records = [info for info in sub_node if isinstance(info, RecordInfo)]
            output.append(_get_namespace_records_block(records))

            # TODO(MarshalX): generate namespace record classes!

            methods = [info for info in sub_node if isinstance(info, MethodInfo)]
            output.append(_get_namespace_methods_block(methods, sync=sync))


def generate_namespaces() -> None:
    namespace_tree = build_namespaces()

    for sync in (True, False):
        generated_code_lines_buffer = []
        _generate_namespace_in_output(namespace_tree, generated_code_lines_buffer, sync=sync)

        code = join_code([_get_namespace_imports(), *generated_code_lines_buffer])

        filename = _NAMESPACES_SYNC_FILENAME if sync else _NAMESPACES_ASYNC_FILENAME
        filepath = _NAMESPACES_OUTPUT_DIR.joinpath(filename)

        write_code(filepath, code)
        format_code(filepath)

        # TODO(MarshalX): generate ClientRaw as root of namespaces


if __name__ == '__main__':
    generate_namespaces()