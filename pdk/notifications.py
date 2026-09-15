# -*- coding: utf-8 -*-
"""智播豆客户端通知与升级公告管理器。

实现特性：
1. 24 小时检查周期：默认每 24 小时才向服务端发一次 HTTP 请求，避免频繁打扰；
2. 本地已读状态持久化：已读通知长期保存在本地 ~/.ZhiBoDouData/notifications_app_{appId}.json；
3. 红点角标计算：首次获取未读通知时展示「+N」红色徽标；点击浏览后红点消失；
4. 历史保留：已读通知下一次拉取时仍展示在历史列表中，但不重复计入红点数量；
5. 强弹窗感知：若通知包含 isPopup=1 且未读，客户端启动或拉取时自动弹窗提醒。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests

from core.config import APP_VERSION, USER_DATA_PATH


class NotificationLocalStore:
    """客户端本地通知频控与已读持久化管理器。"""

    def __init__(self, store_dir: Optional[Path | str] = None, app_id: int = 3):
        if store_dir is not None:
            self.store_dir = Path(store_dir)
        else:
            self.store_dir = Path(USER_DATA_PATH)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.app_id = int(app_id)
        self.file_path = self.store_dir / f"notifications_app_{self.app_id}.json"
        self.last_check_ts = 0
        self.read_ids: set[str] = set()
        self.cached_list: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.file_path.exists():
            try:
                data = json.loads(self.file_path.read_text(encoding="utf-8"))
                self.last_check_ts = int(data.get("last_check_ts", 0))
                self.read_ids = set(str(x) for x in data.get("read_ids", []))
                self.cached_list = list(data.get("cached_list", []))
                return
            except Exception:
                pass
        self.last_check_ts = 0
        self.read_ids = set()
        self.cached_list = []

    def _save(self) -> None:
        data = {
            "last_check_ts": self.last_check_ts,
            "read_ids": sorted(list(self.read_ids)),
            "cached_list": self.cached_list,
        }
        try:
            self.file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def should_fetch(self, interval_seconds: int = 86400) -> bool:
        """检查距上次拉取是否已满周期（默认 24 小时）；无缓存时必须拉取。"""
        now = int(time.time())
        return (now - self.last_check_ts >= interval_seconds) or not self.cached_list

    def save_fetched(self, notifications: list[dict[str, Any]]) -> None:
        """更新拉取结果并记录当前拉取时间戳。"""
        self.last_check_ts = int(time.time())
        self.cached_list = list(notifications)
        self._save()

    def get_unread_count(self) -> int:
        """计算未读通知数量。已读的通知不会计入。"""
        count = 0
        for item in self.cached_list:
            nid = str(item.get("id", ""))
            if nid and nid not in self.read_ids:
                count += 1
        return count

    def mark_all_as_read(self) -> None:
        """将当前缓存的所有通知标记为已读（红点消失，历史继续保留）。"""
        for item in self.cached_list:
            nid = str(item.get("id", ""))
            if nid:
                self.read_ids.add(nid)
        self._save()

    def get_unread_popups(self) -> list[dict[str, Any]]:
        """获取所有未读且需要强弹窗的通知列表。"""
        popups = []
        for item in self.cached_list:
            nid = str(item.get("id", ""))
            if item.get("isPopup") == 1 and nid and nid not in self.read_ids:
                popups.append(item)
        return popups

    def reset_for_test(self) -> None:
        self.last_check_ts = 0
        self.read_ids.clear()
        self.cached_list.clear()
        self._save()


def resolve_pdk_server_endpoint() -> tuple[str, int]:
    """解析当前客户端连接的 PDK 服务地址与 AppID。"""
    # 优先环境变量
    base_url = (os.getenv("PDK_BASE_URL") or "").strip()
    raw_app_id = (os.getenv("PDK_APP_ID") or "").strip()
    app_id = int(raw_app_id) if raw_app_id.isdigit() else 3

    if not base_url:
        # 其次读取 client-update.json 配置
        try:
            from client_update.config import UpdateConfig
            cfg = UpdateConfig.load()
            base_url = cfg.server_base_url
            app_id = cfg.app_id
        except Exception:
            pass

    if not base_url:
        # 默认生产服务端地址
        base_url = "https://pdk.graddu.com"

    return base_url.rstrip("/"), app_id


def extract_notification_list(raw_data: Any) -> list[dict[str, Any]]:
    """从服务端返回的 data 字段中提取通知列表（兼容 dict 带 list / records 或直接为 list）。"""
    if isinstance(raw_data, list):
        return raw_data
    if isinstance(raw_data, dict):
        if isinstance(raw_data.get("list"), list):
            return raw_data["list"]
        if isinstance(raw_data.get("records"), list):
            return raw_data["records"]
    return []


def fetch_notifications(
    base_url: Optional[str] = None,
    app_id: Optional[int] = None,
    current_version: str = "",
    timeout: int = 6,
) -> list[dict[str, Any]]:
    """向服务端 HTTP 接口拉取针对该 appId 的生效通知与升级公告。"""
    def_url, def_app_id = resolve_pdk_server_endpoint()
    url = (base_url or def_url).rstrip("/") + "/api/v1/client/notifications"
    aid = app_id if app_id is not None else def_app_id
    ver = current_version or APP_VERSION

    params = {"appId": aid, "currentVersion": ver}
    headers = {
        "Accept": "application/json",
        "User-Agent": f"Zhibodou-Desktop/{APP_VERSION}",
        "X-PDK-App-ID": str(aid),
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                return extract_notification_list(data.get("data"))
    except Exception:
        # 静默记录异常，不影响主流程启动
        pass
    return []
