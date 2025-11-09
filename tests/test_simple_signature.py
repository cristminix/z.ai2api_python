#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Alat uji tanda tangan sederhana
"""

import sys
import os

# Tambahkan direktori root proyek ke path Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 直接导入签名模块，避免导入整个应用
import importlib.util
spec = importlib.util.spec_from_file_location("signature", os.path.join(os.path.dirname(os.path.dirname(__file__)), "app/utils/signature.py"))
signature_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signature_module)

generate_signature = signature_module.generate_signature


if __name__ == "__main__":
    # Contoh penggunaan
    e_value = "requestId,eef12d6c-6dc9-47a0-aae8-b9f3454f98c5,timestamp,1761038714733,user_id,21ea9ec3-e492-4dbb-b522-fc0eaf64f0f6"
    t_value = "hi"
    r_value = 1761038714733
    result = generate_signature(e_value, t_value, r_value)
    print(f"Tanda tangan yang dihasilkan: {result['signature']}")
    print(f"Stempel waktu: {result['timestamp']}")
    
    # 验证函数是否正常工作
    assert "signature" in result
    assert "timestamp" in result
    assert result["timestamp"] == str(r_value)
    print("Uji fungsi tanda tangan berhasil!")
