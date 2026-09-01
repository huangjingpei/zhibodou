# -*- coding: utf-8 -*-
"""本地登录凭据持久化（加密保存手机号/密码/卡密，供「记住我」自动回填）。

安全边界说明（重要）：
- 本机持久化凭据无法做到"绝对安全"——加密密钥也必须落盘，拿到本机文件的人
  理论上都能解密。这里用 Fernet 对称加密只是避免把密码以明文躺在磁盘上，属于
  "防君子不防小人"的折衷，与浏览器的本地凭据存储同一档位。
- 文件落在 USER_DATA_PATH（~/.ZhiBoDouData/），该目录已被 .gitignore 忽略，
  不会进版本库。
- 缺 cryptography 依赖时降级为明文 JSON 并打 warning（不崩溃、不影响登录）。

调用约定：
- save_credentials(phone, password, card_key)：登录成功时调用，失败返回 False。
- load_credentials() -> dict(phone,password,card_key) | None：构造登录窗时回填。
- clear_credentials()：需要"退出即清除"时调用（当前需求保留凭据，故不主动调）。
"""
import base64
import json
import os

from core.config import USER_DATA_PATH

CREDENTIALS_FILE = os.path.join(USER_DATA_PATH, "credentials.json")
KEY_FILE = os.path.join(USER_DATA_PATH, "credentials.key")


def _fernet_key():
    """读取或生成 Fernet 密钥；cryptography 不可用时返回 None（走降级）。"""
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as fh:
                return fh.read().strip()
        except Exception:
            return None
    key = Fernet.generate_key()
    try:
        with open(KEY_FILE, "wb") as fh:
            fh.write(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        # 写盘失败也返回 key，至少本次会话能用（下次重启会重新尝试落盘）
        pass
    return key


def save_credentials(phone, password, card_key=""):
    """加密保存凭据。任何异常都返回 False，绝不向上抛，避免阻塞登录成功流程。"""
    phone = phone or ""
    password = password or ""
    card_key = card_key or ""
    payload = json.dumps(
        {"phone": phone, "password": password, "card_key": card_key},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        from cryptography.fernet import Fernet
        key = _fernet_key()
        if key is None:
            raise RuntimeError("cryptography 不可用")
        token = Fernet(key).encrypt(payload)
        data = {"v": 1, "enc": "fernet",
                "data": base64.b64encode(token).decode("ascii")}
    except Exception as exc:
        # 降级：明文 JSON（仅本机文件，已被 .gitignore 忽略）
        import warnings
        warnings.warn("凭据已降级为明文保存（缺少 cryptography）：%s" % exc)
        data = {"v": 1, "enc": "plain", "data": payload.decode("utf-8")}
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        try:
            os.chmod(CREDENTIALS_FILE, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False


def load_credentials():
    """读取凭据。返回 dict(phone,password,card_key)；不存在/损坏/解密失败返回 None。"""
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    enc = data.get("enc")
    raw = data.get("data")
    try:
        if enc == "fernet":
            from cryptography.fernet import Fernet
            key = _fernet_key()
            if key is None:
                return None
            token = base64.b64decode(raw)
            obj = json.loads(Fernet(key).decrypt(token).decode("utf-8"))
        elif enc == "plain":
            obj = json.loads(raw) if isinstance(raw, str) else raw
        else:
            return None
        return {
            "phone": obj.get("phone", ""),
            "password": obj.get("password", ""),
            "card_key": obj.get("card_key", ""),
        }
    except Exception:
        return None


def clear_credentials():
    """清空已保存凭据。返回是否操作成功。"""
    try:
        if os.path.exists(CREDENTIALS_FILE):
            os.remove(CREDENTIALS_FILE)
        return True
    except Exception:
        return False
