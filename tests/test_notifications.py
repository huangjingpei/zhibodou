# -*- coding: utf-8 -*-
"""智播豆客户端通知与版本升级公告系统单元测试。"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from pdk.notifications import NotificationLocalStore, fetch_notifications
from ui.notification_dialog import NotificationDialog


class NotificationStoreAndFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="zbd_notice_test_"))
        self.app_id = 3
        self.store = NotificationLocalStore(store_dir=self.temp_dir, app_id=self.app_id)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_state_should_fetch(self):
        """无本地缓存时，首发启动必须发起拉取。"""
        self.assertTrue(self.store.should_fetch(interval_seconds=86400))
        self.assertEqual(self.store.get_unread_count(), 0)

    def test_save_fetched_and_unread_count(self):
        """测试拉取结果存储后角标未读数计算以及 24 小时频控锁定。"""
        sample_notices = [
            {
                "id": 1,
                "appId": 3,
                "noticeType": "UPDATE",
                "title": "v1.8.0 版本升级公告",
                "content": "优化 MediaMTX 推流性能与重连机制",
                "targetVersion": "1.8.0",
                "downloadUrl": "https://pdk.graddu.com/releases/zhibodou-1.8.0.exe",
                "isPopup": 1,
            },
            {
                "id": 2,
                "appId": 3,
                "noticeType": "ANNOUNCEMENT",
                "title": "系统维护预告",
                "content": "将于凌晨进行例行维护",
                "isPopup": 0,
            },
        ]
        self.store.save_fetched(sample_notices)

        # 初始未读数为 2
        self.assertEqual(self.store.get_unread_count(), 2)
        # 且已进入 24 小时检查频控周期，不再重复发起网络请求
        self.assertFalse(self.store.should_fetch(interval_seconds=86400))
        # 强弹窗检测：有 1 条未读且 isPopup=1
        popups = self.store.get_unread_popups()
        self.assertEqual(len(popups), 1)
        self.assertEqual(popups[0]["id"], 1)

    def test_mark_all_as_read_preserves_history_and_clears_badge(self):
        """测试全部已读后未读数归零、历史记录仍然完整保留。"""
        sample_notices = [
            {"id": 10, "title": "公告 A"},
            {"id": 11, "title": "公告 B"},
        ]
        self.store.save_fetched(sample_notices)
        self.assertEqual(self.store.get_unread_count(), 2)

        # 用户浏览弹窗后标记全部已读
        self.store.mark_all_as_read()

        # 红点清零
        self.assertEqual(self.store.get_unread_count(), 0)
        # 弹窗列表中的历史数据完整保留
        self.assertEqual(len(self.store.cached_list), 2)
        # 强弹窗列表为空（因为已被读取）
        self.assertEqual(len(self.store.get_unread_popups()), 0)

    def test_persistence_and_subsequent_pull_no_badge(self):
        """验证已读持久化后，重启程序或隔天再次拉取相同通知不会复现红点，新增通知才 +1。"""
        # 第一轮：拉取 ID=20 的通知并已读
        self.store.save_fetched([{"id": 20, "title": "旧通知"}])
        self.store.mark_all_as_read()
        self.assertEqual(self.store.get_unread_count(), 0)

        # 模拟重启程序重新加载本地存储
        reloaded_store = NotificationLocalStore(store_dir=self.temp_dir, app_id=self.app_id)
        self.assertEqual(reloaded_store.get_unread_count(), 0)
        self.assertEqual(len(reloaded_store.cached_list), 1)

        # 模拟 24 小时后服务端再次返回旧通知 ID=20 以及一条新发布的通知 ID=21
        second_fetch = [
            {"id": 20, "title": "旧通知"},
            {"id": 21, "title": "新发布通知 v1.9.0"},
        ]
        reloaded_store.save_fetched(second_fetch)

        # ID=20 已经在已读集合中，因此仅 ID=21 计入未读数，未读数为 1 (+1)
        self.assertEqual(reloaded_store.get_unread_count(), 1)
        self.assertEqual(len(reloaded_store.cached_list), 2)

    def test_24_hour_interval_expiration(self):
        """测试 24 小时阈值到达后重新允许发起拉取。"""
        self.store.save_fetched([{"id": 30, "title": "测试"}])
        self.assertFalse(self.store.should_fetch(interval_seconds=86400))

        # 模拟距离上次检查已过去 25 小时
        self.store.last_check_ts = int(time.time()) - 25 * 3600
        self.assertTrue(self.store.should_fetch(interval_seconds=86400))

    def test_fetch_notifications_mock(self):
        """测试 HTTP 拉取解析逻辑（支持直接 list 格式与后端包装的 dict list 格式）。"""
        with patch("requests.get") as mock_get:
            # 1. 测试直接 list 格式
            mock_resp1 = MagicMock()
            mock_resp1.status_code = 200
            mock_resp1.json.return_value = {
                "code": 200,
                "message": "success",
                "data": [{"id": 99, "title": "Mock 通知"}],
            }
            mock_get.return_value = mock_resp1
            items = fetch_notifications(base_url="http://127.0.0.1:8080", app_id=3)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], 99)

            # 2. 测试后端标准包装格式 {"list": [...], "total": 1}
            mock_resp2 = MagicMock()
            mock_resp2.status_code = 200
            mock_resp2.json.return_value = {
                "code": 200,
                "message": "操作成功",
                "data": {
                    "list": [{"id": 100, "title": "Spring Boot 结构通知"}],
                    "total": 1,
                    "appId": 3,
                },
            }
            mock_get.return_value = mock_resp2
            items2 = fetch_notifications(base_url="http://127.0.0.1:8080", app_id=3)
            self.assertEqual(len(items2), 1)
            self.assertEqual(items2[0]["id"], 100)

    def test_notification_dialog_ui(self):
        """测试弹窗界面构造及标记已读回调。"""
        self.store.save_fetched([
            {
                "id": 100,
                "noticeType": "UPDATE",
                "title": "版本升级测试",
                "content": "测试升级说明",
                "targetVersion": "1.8.0",
                "downloadUrl": "https://example.com/update.exe",
            }
        ])
        callback_called = []
        dlg = NotificationDialog(None, self.store, on_read_changed=lambda: callback_called.append(True))
        self.assertIsNotNone(dlg)

        dlg._on_close_clicked()
        self.assertTrue(callback_called)
        self.assertEqual(self.store.get_unread_count(), 0)
        dlg.close()

    def test_notification_dialog_accordion_toggle(self):
        """测试通知弹窗手风琴折叠展开交互：
        1. 默认最新一条（第 0 项）展开，其他项折叠单行显示；
        2. 点击第 1 项后，第 0 项缩放折叠，第 1 项展开显示全部；
        3. 再次点击第 1 项可折叠该项。
        """
        self.store.save_fetched([
            {
                "id": 201,
                "noticeType": "UPDATE",
                "title": "最新更新 v2.0.0",
                "content": "最新特性介绍",
                "targetVersion": "2.0.0",
            },
            {
                "id": 202,
                "noticeType": "ANNOUNCEMENT",
                "title": "系统维护通知",
                "content": "维护内容详情",
            },
            {
                "id": 203,
                "noticeType": "ANNOUNCEMENT",
                "title": "业务公告",
                "content": "公告正文",
            },
        ])
        dlg = NotificationDialog(None, self.store)
        self.assertEqual(len(dlg.cards), 3)

        # 1. 默认状态：第 0 项展开，其余折叠单行
        self.assertTrue(dlg.cards[0].is_expanded())
        self.assertFalse(dlg.cards[1].is_expanded())
        self.assertFalse(dlg.cards[2].is_expanded())
        self.assertEqual(dlg.cards[0].arrow_lbl.text().strip(), "▲")
        self.assertEqual(dlg.cards[1].arrow_lbl.text().strip(), "▼")

        # 2. 点击第 1 项：当前已展开的第 0 项缩放折叠，第 1 项展开显示全部
        dlg._on_card_toggle(1)
        self.assertFalse(dlg.cards[0].is_expanded())
        self.assertTrue(dlg.cards[1].is_expanded())
        self.assertFalse(dlg.cards[2].is_expanded())
        self.assertEqual(dlg.cards[0].arrow_lbl.text().strip(), "▼")
        self.assertEqual(dlg.cards[1].arrow_lbl.text().strip(), "▲")

        # 3. 再次点击第 1 项：折叠该项
        dlg._on_card_toggle(1)
        self.assertFalse(dlg.cards[1].is_expanded())

        # 4. 点击第 2 项：展开第 2 项
        dlg._on_card_toggle(2)
        self.assertTrue(dlg.cards[2].is_expanded())
        self.assertFalse(dlg.cards[0].is_expanded())
        self.assertFalse(dlg.cards[1].is_expanded())

        dlg.close()


if __name__ == "__main__":
    unittest.main()
