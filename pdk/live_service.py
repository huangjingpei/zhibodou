# -*- coding: utf-8 -*-
"""ZHIBO_LIVE 推流票据编排（appId=3 专属能力）。

推流地址由后端短效签发（MediaMTX 鉴权方案，见 E:\\pdk\\docs\\ZHIBO_LIVE_*.md）：
每次开始直播前申请 publish ticket，拿到不透明 publishUrl 立即交给推流器。
安全红线（来自接入指南第 10.2 节）：
  * publishUrl 不解析、不重新拼接；
  * 不保存到数据库/配置文件、不写日志、不进 UI、不进剪贴板；
  * 超时或断线后立即丢弃，重连必须重新申请（旧票据绑定原连接，重放会被拒）。

UI / sessions 只调用本模块，不直接接触票据接口与 PdkClient。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

from pdk import auth_service as _auth
from pdk.pdk_client import PdkClientError

# 遗留会话中「占着坑」的状态：申请票据前需要先释放，否则服务端返回 40971。
_ACTIVE_STATES = {"ISSUED", "AUTHORIZED", "LIVE"}


class LivePushError(RuntimeError):
    """推流票据申请/释放失败；message 已脱敏，可直接展示给用户。"""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


def is_backend_managed() -> bool:
    """当前会话是否由后端管理推流地址（真实 PDK 登录）。

    False 时调用方回落本地 RTMP 地址（本地 MediaMTX / 开发场景）。"""
    return _auth.current_client() is not None


def acquire_push_ticket(title: str = "") -> dict[str, Any]:
    """申请短效推流票据。

    返回 {"publish_url", "session_no", "expires_at", "ttl_seconds", "status"}。
    服务端返回 40971（已有活动会话）时，同步释放遗留会话并等待服务端落库后重试
    （最多 3 次，避免释放请求与重试请求竞态）；其余业务错误包装为 LivePushError
    （message 来自服务端，可直接展示）。
    """
    client = _auth.current_client()
    if client is None:
        raise LivePushError("当前没有有效的 PDK 登录会话，请重新登录")
    last_exc: Optional[PdkClientError] = None
    for attempt in range(3):
        try:
            return _request_ticket(client, title)
        except PdkClientError as exc:
            if exc.code != 40971:
                raise LivePushError(_auth.format_error(exc), code=exc.code) from exc
            last_exc = exc
        # 40971：存在遗留活动会话。同步释放（必须等停止请求真正返回再重试）。
        _release_leftover_sessions_blocking(client)
        time.sleep(0.5 * (attempt + 1))
    raise LivePushError(_auth.format_error(last_exc), code=last_exc.code)


def _request_ticket(client: Any, title: str) -> dict[str, Any]:
    data = client.live_publish_ticket(title=title) or {}
    publish_url = str(data.get("publishUrl") or "").strip()
    session_no = str(data.get("streamSessionNo") or "").strip()
    if not publish_url or not session_no:
        raise LivePushError("服务端未返回有效推流地址，请稍后重试")
    return {
        "publish_url": publish_url,
        "session_no": session_no,
        "expires_at": str(data.get("expiresAt") or ""),
        "ttl_seconds": int(data.get("ticketTtlSeconds") or 0),
        "status": str(data.get("status") or "ISSUED"),
    }


def release_stream(session_no: str) -> None:
    """停止推流会话（异步、尽力而为）。重复停止已结束会话可按成功处理。"""
    if not session_no:
        return
    client = _auth.current_client()
    if client is None:
        # 会话已随登录失效（服务端会自行清理对应许可证的流）。
        print("[直播会话] 登录会话已失效，跳过服务端停止请求")
        return
    threading.Thread(target=_stop_quietly, args=(client, session_no),
                     daemon=True).start()


def _release_leftover_sessions_blocking(client: Any) -> int:
    """同步释放当前许可证的遗留活动会话（ISSUED/AUTHORIZED/LIVE）。

    必须阻塞等待每个停止请求返回：后端 stop 同步置 ENDED，若不等待，
    紧随其后的票据申请会再次命中 40971。返回成功释放的会话数。"""
    released = 0
    try:
        sessions = client.live_streams_current() or []
    except PdkClientError as exc:
        print(f"[直播会话] 查询遗留会话失败（继续重试申请）: {_safe_message(exc)}")
        return 0
    for item in sessions:
        session_no = str(item.get("streamSessionNo") or "").strip()
        status = str(item.get("status") or "").upper()
        if session_no and status in _ACTIVE_STATES:
            print(f"[直播会话] 发现遗留会话 {session_no[:16]}…（{status}），先释放")
            if _stop_quietly(client, session_no):
                released += 1
    return released


def _stop_quietly(client: Any, session_no: str) -> bool:
    """同步请求服务端停止会话；返回是否成功。失败打印并吞掉异常。"""
    try:
        client.live_stream_stop(session_no)
        print(f"[直播会话] 已通知服务端停止: session={session_no[:16]}…")
        return True
    except Exception as exc:
        print(f"[直播会话] 释放会话失败（忽略）: session={session_no[:16]}… err={_safe_message(exc)}")
        return False


def _safe_message(exc: BaseException) -> str:
    """错误文本兜底脱敏：PdkClientError 的 message 不含票据；其他异常只取类名。"""
    if isinstance(exc, PdkClientError):
        return f"{exc.message}（code={exc.code}）"
    return exc.__class__.__name__


def redact_host(publish_url: str) -> str:
    """从 publishUrl 提取 host:port 用于安全日志；不含路径与票据查询参数。"""
    try:
        parsed = urlparse(publish_url)
        return parsed.netloc or "未知服务器"
    except Exception:
        return "未知服务器"


def describe_session(session_no: Optional[str]) -> str:
    """UI 展示用的会话标识（截断，不含 publishUrl）。"""
    if not session_no:
        return ""
    return f"{session_no[:18]}…" if len(session_no) > 18 else session_no
