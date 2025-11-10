#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Modul penanganan panggilan alat
"""

import json
import re
import time
from typing import Dict, List, Any, Optional, Tuple
from app.utils.logger import get_logger

logger = get_logger()


def convert_schema_to_typescript_type(schema: Dict[str, Any]) -> str:
    """
    Convert JSON schema to TypeScript type definition
    Based on the approach in generate-tool-calling.md
    """
    if not schema:
        return 'any'

    if '$ref' in schema:
        return schema['$ref'].replace('#/definitions/', '')

    schema_type = schema.get('type', '')
    if schema_type == 'string':
        if 'enum' in schema:
            return ' | '.join(f'"{e}"' for e in schema['enum'])
        return 'string'
    elif schema_type in ['number', 'integer']:
        return 'number'
    elif schema_type == 'boolean':
        return 'boolean'
    elif schema_type == 'object':
        properties = schema.get('properties', {})
        if properties:
            prop_defs = []
            for key, value in properties.items():
                is_required = key in schema.get('required', [])
                optional_marker = '' if is_required else '?'
                prop_defs.append(f"{key}{optional_marker}: {convert_schema_to_typescript_type(value)};")
            return f"{{ {' '.join(prop_defs)} }}"
        return "{ }"
    elif schema_type == 'array':
        items_schema = schema.get('items', {})
        return f"{convert_schema_to_typescript_type(items_schema)}[]"
    elif schema_type == 'null':
        return 'null'
    else:
        return 'any'


def generate_function_typescript_interface(tool: Dict[str, Any]) -> str:
    """
    Generate TypeScript interface for a function tool
    Based on the approach in generate-tool-calling.md
    """
    if tool.get("type") != "function":
        return ""

    function_spec = tool.get("function", {})
    function_name = function_spec.get("name", "unknown")
    parameters = function_spec.get("parameters", {})

    if not parameters or parameters.get("type") != "object":
        return f"function {function_name}(): any;"

    properties = parameters.get("properties", {})
    if not properties:
        return f"function {function_name}(): any;"

    # Generate parameter list
    param_defs = []
    for param_name, param_details in properties.items():
        is_required = param_name in parameters.get('required', [])
        optional_marker = '' if is_required else '?'
        param_type = convert_schema_to_typescript_type(param_details)
        param_defs.append(f"{param_name}{optional_marker}: {param_type}")

    params_str = ", ".join(param_defs)
    return f"function {function_name}({params_str}): any;"


def generate_tool_prompt(tools: Optional[List[Dict[str, Any]]]) -> str:
    """
    Hasilkan petunjuk panggilan alat
    Konversi definisi alat OpenAI ke format TypeScript interface berdasarkan pendekatan generate-tool-calling.md

    Args:
        tools: Daftar definisi alat dalam format OpenAI

    Returns:
        str: Instruksi penggunaan alat dalam format TypeScript interface
    """
    if not tools or len(tools) == 0:
        return ""

    # Gunakan pendekatan dari generate-tool-calling.md secara keseluruhan
    conversion = "// The current environment gives you access to the following functions to use as tools:\n"

    for tool in filter(lambda x: x.get('type') == 'function', tools):
        converted = generate_function_typescript_interface(tool)
        function_description = tool.get("function", {}).get("description", "")
        conversion += f"// {function_description}\n{converted}\n"

    # Tambahkan interface struktur balasan berdasarkan generate-tool-calling.md
    conversion += """
// Reply interface structure
interface Reply {
    type: string;
};

// FunctionCall interface extending Reply
// Must match one of the above function definitions
interface FunctionCall extends Reply {
    type: "functionCall";
    name: string; /* function name */
    arguments: {
        name: string;
        value: any;
    }[];
};

// Default reply
// Message interface extending Reply
interface Message extends Reply {
    type: "message";
    content: string; // do not mention the details of your tools
};

Return a valid JSON object conforming to the Reply interface.
"""

    logger.debug(f"Menghasilkan prompt alat TypeScript interface, berisi {len(list(filter(lambda x: x.get('type') == 'function', tools)))} definisi alat")
    return conversion


def process_messages_with_tools(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: str = "auto"
) -> List[Dict[str, Any]]:
    """
    Suntikkan definisi alat ke daftar pesan dalam format TypeScript interface

    Args:
        messages: Daftar pesan asli
        tools: Daftar definisi alat
        tool_choice: Strategi pemilihan alat ("auto", "none", dll)

    Returns:
        List[Dict]: Daftar pesan yang telah diproses
    """
    if not tools or tool_choice == "none":
        return messages

    tools_prompt = generate_tool_prompt(tools)
    if not tools_prompt:
        return messages

    processed = []
    has_system = any(m.get("role") == "system" for m in messages)

    if has_system:
        # Jika ada pesan system, tambahkan prompt alat ke pesan system pertama
        for msg in messages:
            if msg.get("role") == "system":
                new_msg = msg.copy()
                content = new_msg.get("content", "")
                if isinstance(content, list):
                    # Konten multimodal
                    content_str = " ".join([
                        item.get("text", "") if item.get("type") == "text" else ""
                        for item in content
                    ])
                else:
                    content_str = str(content)
                new_msg["content"] = content_str + tools_prompt
                processed.append(new_msg)
            else:
                processed.append(msg)
    else:
        # Tidak ada pesan system, buat pesan system baru
        processed.append({
            "role": "system",
            "content": tools_prompt
        })
        processed.extend(messages)

    logger.debug(f"Petunjuk alat telah disuntikkan ke daftar pesan, total {len(processed)} pesan")
    return processed


def parse_and_extract_tool_calls(content: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """
    Ekstrak JSON tool_calls dari konten respons

    Args:
        content: Konten teks yang dikembalikan model

    Returns:
        Tuple[Optional[List], str]: (Daftar tool_calls yang diekstrak, konten yang dibersihkan)
    """
    if not content or not content.strip():
        return None, content

    tool_calls = None
    cleaned_content = content

    # Metode 1: Coba parsing tool_calls dari blok kode JSON (format lama)
    # Cocokkan ```json ... ``` atau ```...```
    json_block_pattern = r'```(?:json)?\s*\n?(\{[\s\S]*?\})\s*\n?```'
    json_blocks = re.findall(json_block_pattern, content)

    for json_str in json_blocks:
        try:
            parsed_data = json.loads(json_str)
            if "tool_calls" in parsed_data:
                tool_calls = parsed_data["tool_calls"]
                if tool_calls and isinstance(tool_calls, list):
                    # Pastikan field arguments adalah string
                    for tc in tool_calls:
                        if tc.get("function"):
                            func = tc["function"]
                            if func.get("arguments"):
                                if isinstance(func["arguments"], dict):
                                    # Konversi objek ke string JSON
                                    func["arguments"] = json.dumps(func["arguments"], ensure_ascii=False)
                                elif not isinstance(func["arguments"], str):
                                    func["arguments"] = str(func["arguments"])
                    logger.debug(f"Ekstrak {len(tool_calls)} panggilan alat dari blok JSON")
                    break
        except json.JSONDecodeError:
            continue

    # Metode 2: Coba cari objek JSON langsung dari teks (format lama)
    if not tool_calls:
        # Cari objek JSON yang mengandung "tool_calls"
        i = 0
        scannable_text = content
        while i < len(scannable_text):
            if scannable_text[i] == '{':
                # Coba temukan kurung tutup yang cocok
                brace_count = 1
                j = i + 1
                in_string = False
                escape_next = False

                while j < len(scannable_text) and brace_count > 0:
                    if escape_next:
                        escape_next = False
                    elif scannable_text[j] == '\\':
                        escape_next = True
                    elif scannable_text[j] == '"':
                        in_string = not in_string
                    elif not in_string:
                        if scannable_text[j] == '{':
                            brace_count += 1
                        elif scannable_text[j] == '}':
                            brace_count -= 1
                    j += 1

                if brace_count == 0:
                    # Temukan objek JSON lengkap
                    json_candidate = scannable_text[i:j]
                    try:
                        parsed_data = json.loads(json_candidate)
                        if "tool_calls" in parsed_data:
                            tool_calls = parsed_data["tool_calls"]
                            if tool_calls and isinstance(tool_calls, list):
                                # Pastikan field arguments adalah string
                                for tc in tool_calls:
                                    if tc.get("function"):
                                        func = tc["function"]
                                        if func.get("arguments"):
                                            if isinstance(func["arguments"], dict):
                                                func["arguments"] = json.dumps(func["arguments"], ensure_ascii=False)
                                            elif not isinstance(func["arguments"], str):
                                                func["arguments"] = str(func["arguments"])
                                logger.debug(f"Ekstrak {len(tool_calls)} panggilan alat dari JSON sebaris")
                                break
                    except json.JSONDecodeError:
                        pass

                i = j
            else:
                i += 1

    # Metode 3: Coba ekstrak format TypeScript interface (format baru)
    if not tool_calls:
        # Cari objek JSON dengan tipe "functionCall" sesuai interface kita
        i = 0
        scannable_text = content
        while i < len(scannable_text):
            if scannable_text[i] == '{':
                # Coba temukan kurung tutup yang cocok
                brace_count = 1
                j = i + 1
                in_string = False
                escape_next = False

                while j < len(scannable_text) and brace_count > 0:
                    if escape_next:
                        escape_next = False
                    elif scannable_text[j] == '\\':
                        escape_next = True
                    elif scannable_text[j] == '"':
                        in_string = not in_string
                    elif not in_string:
                        if scannable_text[j] == '{':
                            brace_count += 1
                        elif scannable_text[j] == '}':
                            brace_count -= 1
                    j += 1

                if brace_count == 0:
                    # Temukan objek JSON lengkap
                    json_candidate = scannable_text[i:j]
                    try:
                        parsed_data = json.loads(json_candidate)
                        if parsed_data.get("type") == "functionCall":
                            # Konversi dari format interface TypeScript ke format OpenAI
                            function_call = {
                                "id": f"call_{int(time.time() * 1000)}_{i}",  # Generate ID based on position
                                "type": "function",
                                "function": {
                                    "name": parsed_data.get("name", ""),
                                    "arguments": "{}"  # Default empty arguments
                                }
                            }

                            # Konversi arguments dari format array ke JSON string
                            arguments_array = parsed_data.get("arguments", [])
                            if arguments_array and isinstance(arguments_array, list):
                                # Konversi dari format [{"name": "...", "value": "..."}] ke objek JSON
                                args_obj = {}
                                for arg in arguments_array:
                                    if isinstance(arg, dict) and "name" in arg and "value" in arg:
                                        args_obj[arg["name"]] = arg["value"]

                                function_call["function"]["arguments"] = json.dumps(args_obj, ensure_ascii=False)

                            tool_calls = [function_call]
                            logger.debug(f"Ekstrak panggilan alat dari format interface TypeScript: {function_call}")
                            break
                    except json.JSONDecodeError:
                        pass

                i = j
            else:
                i += 1

    # Metode 4: Coba ekstrak konten pesan dari format TypeScript interface (jika tidak ada tool call)
    if not tool_calls:
        # Cari objek JSON dengan tipe "message" sesuai interface kita
        i = 0
        scannable_text = content
        while i < len(scannable_text):
            if scannable_text[i] == '{':
                # Coba temukan kurung tutup yang cocok
                brace_count = 1
                j = i + 1
                in_string = False
                escape_next = False

                while j < len(scannable_text) and brace_count > 0:
                    if escape_next:
                        escape_next = False
                    elif scannable_text[j] == '\\':
                        escape_next = True
                    elif scannable_text[j] == '"':
                        in_string = not in_string
                    elif not in_string:
                        if scannable_text[j] == '{':
                            brace_count += 1
                        elif scannable_text[j] == '}':
                            brace_count -= 1
                    j += 1

                if brace_count == 0:
                    # Temukan objek JSON lengkap
                    json_candidate = scannable_text[i:j]
                    try:
                        parsed_data = json.loads(json_candidate)
                        if parsed_data.get("type") == "message" and "content" in parsed_data:
                            # Ini adalah pesan biasa, kembalikan konten dan hapus objek JSON dari teks
                            message_content = parsed_data.get("content", "")
                            # Hapus objek JSON dari konten
                            cleaned_content = content.replace(json_candidate, str(message_content), 1)
                            logger.debug(f"Ekstrak konten pesan dari format interface TypeScript: {message_content}")
                            return None, cleaned_content  # Tidak ada tool call, hanya konten yang dibersihkan
                    except json.JSONDecodeError:
                        pass

                i = j
            else:
                i += 1

    # Bersihkan konten - Hapus JSON yang mengandung tool_calls
    if tool_calls:
        cleaned_content = remove_tool_json_content(content)

    return tool_calls, cleaned_content


def remove_tool_json_content(content: str) -> str:
    """
    Hapus panggilan alat JSON dari konten respons

    Args:
        content: Konten respons asli

    Returns:
        str: Konten yang telah dibersihkan
    """
    if not content:
        return content

    # Langkah 1: Hapus bagian yang mengandung tool_calls dari blok kode JSON
    cleaned_text = content

    # Cocokkan ```json ... ``` atau ```...```
    def replace_json_block(match):
        json_content = match.group(1)
        try:
            parsed_data = json.loads(json_content)
            if "tool_calls" in parsed_data or parsed_data.get("type") in ("functionCall", "message"):
                return ""  # Hapus seluruh blok kode
        except json.JSONDecodeError:
            pass
        return match.group(0)  # Pertahankan teks asli

    json_block_pattern = r'```(?:json)?\s*\n?(\{[\s\S]*?\})\s*\n?```'
    cleaned_text = re.sub(json_block_pattern, replace_json_block, cleaned_text)

    # Langkah 2: Hapus tool JSON sebaris - gunakan metode penyeimbangan kurung
    result = []
    i = 0

    while i < len(cleaned_text):
        if cleaned_text[i] == '{':
            # Coba temukan kurung tutup yang cocok
            brace_count = 1
            j = i + 1
            in_string = False
            escape_next = False

            while j < len(cleaned_text) and brace_count > 0:
                if escape_next:
                    escape_next = False
                elif cleaned_text[j] == '\\':
                    escape_next = True
                elif cleaned_text[j] == '"':
                    in_string = not in_string
                elif not in_string:
                    if cleaned_text[j] == '{':
                        brace_count += 1
                    elif cleaned_text[j] == '}':
                        brace_count -= 1
                j += 1

            if brace_count == 0:
                # Temukan objek JSON lengkap, periksa apakah mengandung tool_calls atau functionCall
                json_candidate = cleaned_text[i:j]
                try:
                    parsed = json.loads(json_candidate)
                    if "tool_calls" in parsed or parsed.get("type") in ("functionCall", "message"):
                        # Ini adalah panggilan alat atau pesan, lewati
                        i = j
                        continue
                except json.JSONDecodeError:
                    pass

            # Bukan panggilan alat atau tidak dapat diparsing, pertahankan karakter ini
            result.append(cleaned_text[i])
            i += 1
        else:
            result.append(cleaned_text[i])
            i += 1

    cleaned_result = "".join(result).strip()

    # Hapus baris kosong yang berlebihan
    cleaned_result = re.sub(r'\n{3,}', '\n\n', cleaned_result)

    logger.debug(f"Pembersihan konten selesai, panjang asli: {len(content)}, panjang setelah dibersihkan: {len(cleaned_result)}")
    return cleaned_result


def content_to_string(content: Any) -> str:
    """
    Konversi konten pesan ke string

    Args:
        content: Konten pesan, bisa berupa string atau daftar (multimodal)

    Returns:
        str: Konten dalam format string
    """
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Konten multimodal, ekstrak bagian teks
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
        return " ".join(text_parts)
    else:
        return str(content)
