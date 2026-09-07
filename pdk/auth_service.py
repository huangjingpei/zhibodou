"""智播豆对 PDK 客户端的认证编排层。

UI 只调用本模块，不直接接触 Token、公钥、HTTP Session 或许可证原始响应。
当前会话只保存在内存中；关闭程序或点击退出登录时会调用服务端 logout 并清理。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pdk.pdk_client import PdkClient, PdkClientError
from core.config import APP_VERSION


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class PdkSettings:
    """PDK 连接设置；敏感值通过环境变量提供，不写入源码。"""

    base_url: str
    app_id: int
    public_key_pin: str = ""
    verify_tls: bool = True
    require_https: bool = False
    expected_biz_code: str = ""
    http_debug: bool = False

    @classmethod
    def from_env(cls) -> "PdkSettings":
        # 与 pdk_client.py::_demo 保持一致：未配置时使用 appId=2。
        raw_app_id = (os.getenv("PDK_APP_ID") or "3").strip()
        try:
            app_id = int(raw_app_id)
        except ValueError as exc:
            raise ValueError("PDK_APP_ID 必须是正整数") from exc
        if app_id <= 0:
            raise ValueError("PDK_APP_ID 必须是正整数")
        return cls(
            base_url=(os.getenv("PDK_BASE_URL") or "http://127.0.0.1:8080").strip(),
            app_id=app_id,
            public_key_pin=(os.getenv("PDK_PUBLIC_KEY_PIN") or "").strip(),
            verify_tls=_env_bool("PDK_VERIFY_TLS", True),
            require_https=_env_bool("PDK_REQUIRE_HTTPS", False),
            # demo 只做业务发现，不擅自限制 bizCode；需要固化时再显式配置。
            expected_biz_code=(os.getenv("PDK_BIZ_CODE") or "").strip(),
            http_debug=_env_bool("PDK_HTTP_DEBUG", False),
        )


@dataclass(frozen=True)
class AuthResult:
    """认证成功后供 UI 与业务层读取的脱敏状态快照。"""

    phone: str
    public_config: dict[str, Any] = field(default_factory=dict)
    business: dict[str, Any] = field(default_factory=dict)
    login_data: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)
    device_license: dict[str, Any] = field(default_factory=dict)
    live_media: dict[str, Any] = field(default_factory=dict)

    @property
    def authorization_mode(self) -> str:
        return str(self.business.get("authorizationMode") or
                   self.session.get("authorizationMode") or "")

    @property
    def status(self) -> str:
        return str(self.device_license.get("status") or self.session.get("status") or
                   self.profile.get("status") or "UNKNOWN")

    @property
    def expire_at(self) -> str:
        return str(self.device_license.get("expireAt") or self.session.get("expireAt") or
                   self.profile.get("expireTime") or "")

    @property
    def remaining_calls(self) -> Any:
        value = self.profile.get("remainingCalls")
        return "不限" if value is None else value

    @property
    def masked_phone(self) -> str:
        if len(self.phone) >= 7:
            return f"{self.phone[:3]}****{self.phone[-4:]}"
        return "***"

    def display_detail(self) -> str:
        biz = str(self.business.get("bizCode") or self.session.get("bizCode") or "PDK")
        parts = [self.masked_phone, biz, self.status]
        if self.live_media.get("mediaServerAddress"):
            parts.append("媒体服务已就绪")
        if self.expire_at:
            parts.append(f"到期 {self.expire_at}")
        if self.remaining_calls != "不限":
            parts.append(f"剩余 {self.remaining_calls} 次")
        return "｜".join(parts)


_lock = threading.RLock()
_client: Optional[PdkClient] = None
_auth_result: Optional[AuthResult] = None


def _validate_business(info: dict[str, Any], settings: PdkSettings) -> None:
    expected = settings.expected_biz_code
    actual = str(info.get("bizCode") or "")
    if expected and actual != expected:
        raise PdkClientError(40050, f"业务不匹配：期望 {expected}，实际 {actual or '未知'}")
    if info.get("effectiveStatus") != "AVAILABLE":
        code = 50350 if info.get("configuredStatus") == "ACTIVE" else 40321
        raise PdkClientError(code, str(info.get("unavailableReason") or "当前业务不可用"), data=info)
    if settings.app_id == 3 and actual == "ZHIBO_LIVE":
        media = info.get("liveMedia") or {}
        if not media.get("enabled") or media.get("status") != "AVAILABLE":
            raise PdkClientError(
                50372,
                str(media.get("status") or info.get("unavailableReason") or "当前没有可用直播媒体节点"),
                data=info,
            )


def authenticate(phone: str, password: str, card_key: str = "", *,
                 settings: Optional[PdkSettings] = None,
                 client_factory: Callable[..., PdkClient] = PdkClient) -> AuthResult:
    """完成公共配置、业务发现、登录、会话、资料和许可证校验。"""
    phone = phone.strip()
    card_key = card_key.strip()
    if not phone:
        raise ValueError("手机号不能为空")
    if not password:
        raise ValueError("密码不能为空")

    settings = settings or PdkSettings.from_env()
    candidate = client_factory(
        settings.base_url,
        settings.app_id,
        phone=phone,
        use_crypto=True,
        auto_enable_crypto=True,
        public_key_pin=settings.public_key_pin,
        verify_tls=settings.verify_tls,
        require_https=settings.require_https,
        user_agent=f"Zhibodou-Desktop/{APP_VERSION}",
    )
    if settings.http_debug:
        candidate.on_http = lambda record: print(
            "[PDK-HTTP] %s %s -> HTTP=%s code=%s msg=%s" % (
                record.get("method"), record.get("url"), record.get("httpStatus"),
                record.get("code"), record.get("message"),
            )
        )
    logged_in = False
    try:
        public_config = candidate.fetch_public_config()
        business = candidate.business_info()
        _validate_business(business, settings)
        live_media = business.get("liveMedia") or {}
        login_data = candidate.login(password, phone=phone, card_key=card_key)
        logged_in = True
        session = candidate.verify_session()
        if not session.get("sessionValid") or not session.get("operationAllowedHint"):
            raise PdkClientError(
                40381,
                f"当前授权不可用：status={session.get('status') or 'UNKNOWN'}，"
                f"expireAt={session.get('expireAt') or '未知'}",
                data=session,
            )
        profile = candidate.profile()
        mode = str(business.get("authorizationMode") or session.get("authorizationMode") or "")
        device_license = candidate.device_license_current() if mode == "DEVICE_LICENSE" else {}
        if mode == "DEVICE_LICENSE" and str(device_license.get("status") or "") != "ACTIVE":
            raise PdkClientError(
                40381,
                f"当前设备许可证不可用：status={device_license.get('status') or 'UNKNOWN'}，"
                f"expireAt={device_license.get('expireAt') or '未知'}",
                data=device_license,
            )
        result = AuthResult(
            phone=phone,
            public_config=public_config,
            business=business,
            login_data=login_data,
            session=session,
            profile=profile,
            device_license=device_license,
            live_media=live_media,
        )
    except Exception:
        if logged_in:
            try:
                candidate.logout()
            except Exception:
                candidate.clear_session()
        candidate.close()
        raise

    global _client, _auth_result
    with _lock:
        previous = _client
        _client = candidate
        _auth_result = result
    if previous is not None and previous is not candidate:
        try:
            previous.close()
        except Exception:
            pass
    return result


def current_auth() -> Optional[AuthResult]:
    with _lock:
        return _auth_result


def current_client() -> Optional[PdkClient]:
    """返回当前已登录的 PdkClient，供 live_service 等编排层做受保护请求。

    未登录或会话已被清理时返回 None；调用方据此决定是否回落本地推流地址。"""
    with _lock:
        client = _client
    if client is not None and client.is_logged_in:
        return client
    return None


def is_authenticated() -> bool:
    with _lock:
        return bool(_client is not None and _client.is_logged_in and _auth_result is not None)


def verify_current_session() -> AuthResult:
    """向服务端重新校验当前会话，并原子更新供 UI 使用的脱敏快照。

    用于开始推流等关键操作和主窗口的低频巡检。网络请求在锁内完成，确保不会
    与 logout() 并发关闭同一个 requests.Session；调用方应始终放在工作线程。
    """
    global _auth_result
    with _lock:
        client = _client
        previous = _auth_result
        if client is None or previous is None or not client.is_logged_in:
            raise PdkClientError(40100, "当前没有有效登录会话，请重新登录")

        session = client.verify_session()
        if not session.get("sessionValid") or not session.get("operationAllowedHint"):
            raise PdkClientError(
                40381,
                f"当前授权不可用：status={session.get('status') or 'UNKNOWN'}，"
                f"expireAt={session.get('expireAt') or '未知'}",
                data=session,
            )

        # 当前客户端的 verify_session() 已通过 profile() 获取 raw；优先复用，
        # 避免一次巡检重复发两个完全相同的资料请求。
        raw_profile = session.get("raw")
        profile = raw_profile if isinstance(raw_profile, dict) else client.profile()
        mode = str(previous.business.get("authorizationMode") or
                   session.get("authorizationMode") or "")
        device_license = previous.device_license
        if mode == "DEVICE_LICENSE":
            device_license = client.device_license_current()
            if str(device_license.get("status") or "") != "ACTIVE":
                raise PdkClientError(
                    40381,
                    f"当前设备许可证不可用：status={device_license.get('status') or 'UNKNOWN'}，"
                    f"expireAt={device_license.get('expireAt') or '未知'}",
                    data=device_license,
                )

        refreshed = AuthResult(
            phone=previous.phone,
            public_config=previous.public_config,
            business=previous.business,
            login_data=previous.login_data,
            session=session,
            profile=profile,
            device_license=device_license,
            live_media=previous.live_media,
        )
        _auth_result = refreshed
        return refreshed


def logout() -> None:
    """服务端注销并无条件清理本地 Token/HTTP 资源。"""
    global _client, _auth_result
    with _lock:
        client = _client
        _client = None
        _auth_result = None
    if client is None:
        return
    try:
        if client.is_logged_in:
            # 退出应用不能因服务端不可达卡住 20 秒。
            client.timeout = (2, 5)
            # 注销是正常生命周期事件，不向用户控制台输出一条调试 HTTP 日志。
            client.on_http = None
            client.logout()
    except Exception:
        pass
    finally:
        client.clear_session()
        client.close()


def format_error(exc: BaseException) -> str:
    """生成可直接显示给用户、且不包含 Token/密码的错误文本。"""
    if isinstance(exc, PdkClientError):
        try:
            connection = environment_hint()
        except Exception:
            connection = ""
        suffix = f"\n连接：{connection}" if connection else ""
        return f"{exc.message}\n错误码：{exc.code}\n处理建议：{exc.action}{suffix}"
    return str(exc) or exc.__class__.__name__


def environment_hint() -> str:
    """返回非敏感连接提示，便于现场发现连错服务。"""
    settings = PdkSettings.from_env()
    return f"PDK AppId={settings.app_id}｜{settings.base_url}"
