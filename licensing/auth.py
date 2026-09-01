# -*- coding: utf-8 -*-
"""授权激活：机器码生成、激活码加解密、有效期校验。

激活码是 base64(json + SECRET_KEY)，绑定机器码与手机号，本地落盘校验。
"""
import base64
import hashlib
import json
import os
import platform
import time
import uuid

from core.config import SECRET_KEY, LICENSE_FILE, PHONE_CFG_FILE, DAY_SEC


def save_phone_config(phone):
    try:
        with open(PHONE_CFG_FILE, "w", encoding="utf-8") as f:
            json.dump({"phone": phone}, f, ensure_ascii=False)
    except:
        pass

def load_phone_config():
    if not os.path.exists(PHONE_CFG_FILE):
        return ""
    try:
        with open(PHONE_CFG_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("phone", "")
    except:
        return ""

def get_machine_code():
    return hashlib.md5(f"{platform.processor()}{hex(uuid.getnode())}".encode()).hexdigest().upper()

def encrypt_lic(data):
    return base64.b64encode((json.dumps(data, ensure_ascii=False) + SECRET_KEY).encode()).decode()

def decrypt_lic(enc):
    try:
        raw = base64.b64decode(enc).decode()
        if raw.endswith(SECRET_KEY):
            return json.loads(raw[:-len(SECRET_KEY)])
        return {}
    except:
        return {}

def get_auth_info():
    phone = load_phone_config().strip()
    if len(phone) < 11 or not os.path.exists(LICENSE_FILE):
        return False, 0, 0, 0
    with open(LICENSE_FILE, "r") as f:
        lic = decrypt_lic(f.read().strip())
    if not lic or lic.get("machine_code") != get_machine_code() or lic.get("bind_phone") != phone:
        return False, 0, 0, 0
    remain = max(0, int(lic.get("expire_time", 0) - time.time()))
    return remain > 0, remain, lic.get("days", 0), lic.get("max_client", 0)

def verify_and_save_activate_code(code, phone):
    lic = decrypt_lic(code)
    if not lic or lic.get("machine_code") != get_machine_code():
        return False, "激活码无效或与本机不匹配"
    days, mc = lic.get("days", 0), lic.get("max_client", 0)
    if days <= 0 or mc <= 0:
        return False, "无效的授权信息"
    lic["bind_phone"] = phone
    lic["expire_time"] = time.time() + days * DAY_SEC
    try:
        with open(LICENSE_FILE, "w") as f:
            f.write(encrypt_lic(lic))
        return True, "激活成功"
    except:
        return False, "写入授权文件失败"
