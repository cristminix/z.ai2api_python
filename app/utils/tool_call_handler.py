#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Modul penanganan panggilan alat
"""

import json
import re
from typing import Dict, List, Any, Optional, Tuple
from app.utils.logger import get_logger

logger = get_logger()


def generate_tool_prompt(tools: Optional[List[Dict[str, Any]]]) -> str:
    """
    Hasilkan petunjuk panggilan alat
    Konversi definisi alat OpenAI ke dokumen instruksi format Markdown

    Args:
        tools: Daftar definisi alat dalam format OpenAI

    Returns:
        str: Instruksi penggunaan alat dalam format Markdown
    """
    if not tools or len(tools) == 0:
        return ""

    tool_definitions = []

    for tool in tools:
        if tool.get("type") != "function":
            continue

        function_spec = tool.get("function", {})
        function_name = function_spec.get("name", "unknown")
        function_description = function_spec.get("description", "")
        parameters = function_spec.get("parameters", {})

        # Buat definisi alat yang terstruktur
        tool_info = [
            f"## {function_name}",
            f"**Purpose**: {function_description}"
        ]

        # Tambahkan detail parameter
        parameter_properties = parameters.get("properties", {})
        required_parameters = set(parameters.get("required", []))

        if parameter_properties:
            tool_info.append("**Parameters**:")
            for param_name, param_info in parameter_properties.items():
                param_type = param_info.get("type", "string")
                param_desc = param_info.get("description", "")
                is_required = param_name in required_parameters
                required_str = " (required)" if is_required else " (optional)"
                tool_info.append(f"- `{param_name}` ({param_type}){required_str}: {param_desc}")

        tool_definitions.append("\n".join(tool_info))

    # Gabungkan prompt lengkap
    prompt = (
        "\n\n---\n"
        "# Available Tools\n\n"
        + "\n\n".join(tool_definitions) +
        "\n\n"
        "**Tool Invocation Format**:\n"
        "To use a tool, include a JSON block with this structure:\n"
        '{"tool_calls": [{"id": "call_ID", "type": "function", "function": {"name": "TOOL_NAME", "arguments": "JSON_STRING"}}]}\n\n'
        "**Rules**:\n"
        "- Use tool ONLY when user explicitly requests an action that matches a tool's purpose\n"
        "- For normal conversation, respond naturally WITHOUT any tool calls\n"
        "- The `arguments` must be a JSON string, not an object\n"
        "- Multiple tools can be called by adding more items to the array\n"
        "---\n\n"
    )

    logger.debug(f"Menghasilkan prompt alat, berisi {len(tool_definitions)} definisi alat")
    return prompt


def process_messages_with_tools(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: str = "auto"
) -> List[Dict[str, Any]]:
    """
    Suntikkan definisi alat ke daftar pesan

    Args:
        messages: Daftar pesan asli
        tools: Daftar definisi alat
        tool_choice: Strategi pemilihan alat ("auto", "none", dll.)

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
            "content": f"You are a helpful assistant with access to tools.{tools_prompt}"
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

    # Metode 1: Coba parsing tool_calls dari blok kode JSON
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

    # Metode 2: Coba cari objek JSON langsung dari teks
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
            if "tool_calls" in parsed_data:
                return ""  # Hapus seluruh blok kode
        except json.JSONDecodeError:
            pass
        return match.group(0)  # Pertahankan teks asli

    json_block_pattern = r'```(?:json)?\s*\n?(\{[\s\S]*?\})\s*\n?```'
    cleaned_text = re.sub(json_block_pattern, replace_json_block, cleaned_text)

    # Langkah 2: Hapus tool JSON inline - gunakan metode penyeimbangan kurung
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
                # Temukan objek JSON lengkap, periksa apakah mengandung tool_calls
                json_candidate = cleaned_text[i:j]
                try:
                    parsed = json.loads(json_candidate)
                    if "tool_calls" in parsed:
                        # Ini adalah panggilan alat, lewati
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
        content: Konten pesan, bisa berupa string atau list (multimodal)

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
