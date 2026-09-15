# -*- coding: utf-8 -*-
"""主窗口编排器：组合首页 / 主播 / 观众三个页面（各自对应 ui.panels 子面板），
负责页面导航、定时器与生命周期，不再直接持有任何控件。

具体控件与交互逻辑分散在：
  ui/panels/home.py   — 首页面板
  ui/panels/host.py   — 主播面板（含内嵌 ui/panels/auth.py 授权面板）
  ui/panels/client.py  — 观众面板

授权统一走 PDK 会话（`pdk.auth_service`）：是否允许推流由
`is_authenticated()` 决定；顶部栏提供「退出登录」并返回登录窗口。
业务逻辑一律在 sessions / streaming / capture，本文件只做编排。
"""
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QMainWindow, QStackedWidget, QWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox,
)

from capture.devices import get_all_mic_devices, get_all_speaker_devices
from core.diagnostics import report_fatal
from ui import theme
from sessions.client import ClientStream
from sessions.host import HostStream
from ui.panels.home import HomePanel
from ui.panels.host import HostPanel
from ui.panels.client import ClientPanel

try:
    from pdk import auth_service as pdk_auth
except Exception:  # pragma: no cover
    pdk_auth = None


class _SessionVerifyWorker(QThread):
    verified = pyqtSignal(object)
    failed = pyqtSignal(object)

    def run(self):
        try:
            self.verified.emit(pdk_auth.verify_current_session())
        except BaseException as exc:
            self.failed.emit(exc)


class _LogoutWorker(QThread):
    """执行有界服务端注销；主线程继续绘制“正在退出”状态。"""

    failed = pyqtSignal(object)

    def run(self):
        try:
            if pdk_auth is not None:
                pdk_auth.logout()
        except BaseException as exc:
            self.failed.emit(exc)


class _NotificationWorker(QThread):
    """后台拉取服务端通知列表，避免主线程网络等待。"""

    fetched = pyqtSignal(object)

    def __init__(self, base_url: str, app_id: int, current_version: str):
        super().__init__()
        self.base_url = base_url
        self.app_id = app_id
        self.current_version = current_version

    def run(self):
        try:
            from pdk.notifications import fetch_notifications
            items = fetch_notifications(self.base_url, self.app_id, self.current_version)
            self.fetched.emit(items)
        except Exception:
            self.fetched.emit([])


class MainWin(QMainWindow):
    def __init__(self):
        super().__init__()
        self._logout_requested = False
        self._shutdown_in_progress = False
        self._shutdown_complete = False
        self._logout_worker = None
        self._session_worker = None
        self._authorized_callbacks = []
        self._show_session_error = False
        self.setWindowTitle("智播豆")
        self.resize(1280, 800)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(theme.app_qss())

        self.host_stream = HostStream()
        self.client_stream = ClientStream()

        # 客户端通知与升级公告持久化管理器 (默认 appId=3)
        from pdk.notifications import NotificationLocalStore, resolve_pdk_server_endpoint
        _, default_app_id = resolve_pdk_server_endpoint()
        self.notice_store = NotificationLocalStore(app_id=default_app_id)
        self._notice_worker = None

        # 预览定时器须先于面板创建：HostPanel.__init__ 会持有它
        self.timer = QTimer(self)

        # 面板（build 在 init_ui 中调用，届时互相引用才需要）
        self.home_panel = HomePanel(self)
        self.host_panel = HostPanel(self)
        self.client_panel = ClientPanel(self)

        # 预览定时器：超时回调交由主播面板渲染预览帧 + 巡检推流状态
        self.timer.timeout.connect(self.host_panel.pull_frame)

        # 授权状态巡检定时器：超时回调交由主播页内嵌的授权面板刷新
        self.auth_timer = QTimer(self)
        self.auth_timer.start(1000)

        # 服务端会话低频巡检；本地 token 存在不代表许可证仍然有效。
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(60_000)
        self.session_timer.timeout.connect(self._start_session_check)

        self.all_mics = get_all_mic_devices()
        self.all_speakers = get_all_speaker_devices()
        self.init_ui()
        self.session_timer.start()
        QTimer.singleShot(0, self._start_session_check)
        QTimer.singleShot(1000, lambda: self._check_notifications(force=False))

    def init_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.stack.addWidget(self.home_panel.build(self.stack))
        self.stack.addWidget(self.host_panel.build(self.stack))
        self.stack.addWidget(self.client_panel.build(self.stack))
        # 授权面板在主播页 build 时才创建，故在此连接其刷新回调
        self.auth_timer.timeout.connect(self.host_panel.auth_panel.refresh_status)

    # ---------------------------------------------------------------- 顶部栏
    def _build_topbar(self):
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            f"background-color:{theme.BG_ELEVATED};"
            f"border-bottom:1px solid {theme.BORDER};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)

        brand = QLabel("智播豆")
        brand.setFont(theme.font(theme.FS_H2, bold=True))
        brand.setStyleSheet(theme.label_style(theme.FS_H2, theme.TEXT, bold=True))
        lay.addWidget(brand)

        lay.addStretch(1)

        self.lab_account = QLabel("")
        self.lab_account.setFont(theme.font(theme.FS_SMALL))
        self.lab_account.setStyleSheet(theme.label_style(theme.FS_SMALL, theme.TEXT_MUTED))
        lay.addWidget(self.lab_account)

        # 通知铃铛按钮容器（支持左上角浮动红点角标 +1 / +2）
        self.notice_box = QWidget()
        self.notice_box.setFixedHeight(36)
        notice_lay = QHBoxLayout(self.notice_box)
        notice_lay.setContentsMargins(6, 4, 4, 2)
        notice_lay.setSpacing(0)

        self.btn_notice = QPushButton("🔔 通知公告")
        self.btn_notice.setProperty("ghost", True)
        self.btn_notice.setFixedHeight(30)
        self.btn_notice.setCursor(Qt.PointingHandCursor)
        self.btn_notice.setStyleSheet(f"""
            QPushButton {{
                color: {theme.TEXT_SOFT};
                background: transparent;
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
                padding: 0 10px;
                font-size: {theme.FS_SMALL}pt;
            }}
            QPushButton:hover {{
                color: {theme.TEXT};
                border-color: {theme.PRIMARY};
                background-color: {theme.SURFACE_ALT};
            }}
        """)
        self.btn_notice.clicked.connect(lambda: self.show_notifications_dialog(force=True))
        notice_lay.addWidget(self.btn_notice)

        # 浮动在按钮左上角的红色未读数角标 (+1 / +2 ...)
        self.lab_notice_badge = QLabel("", self.notice_box)
        self.lab_notice_badge.setStyleSheet(f"""
            QLabel {{
                background-color: #ef4444;
                color: #ffffff;
                border: 1.5px solid {theme.BG_ELEVATED};
                border-radius: 8px;
                padding: 0 4px;
                font-size: 9px;
                font-weight: bold;
                min-height: 16px;
            }}
        """)
        self.lab_notice_badge.setAlignment(Qt.AlignCenter)
        self.lab_notice_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lab_notice_badge.hide()
        lay.addWidget(self.notice_box)

        self.btn_logout = QPushButton("退出登录")
        self.btn_logout.setProperty("ghost", True)
        self.btn_logout.setFixedHeight(30)
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        self.btn_logout.clicked.connect(self._request_logout)
        lay.addWidget(self.btn_logout)

        self._refresh_account_label()
        return bar

    def _refresh_account_label(self):
        if pdk_auth is not None:
            result = pdk_auth.current_auth()
            if result is not None:
                self.lab_account.setText("当前账号：%s" % result.masked_phone)
                return
        self.lab_account.setText("未登录")

    # ------------------------------------------------------------ 系统通知与升级公告
    def _refresh_notice_badge(self):
        """根据本地已读状态刷新通知按钮左上角的红点角标 (+1 / +2 等)。"""
        unread = self.notice_store.get_unread_count()
        if unread > 0:
            text = f"+{unread}" if unread <= 99 else "+99"
            self.lab_notice_badge.setText(text)
            self.lab_notice_badge.adjustSize()
            self.lab_notice_badge.move(0, 0)
            self.lab_notice_badge.raise_()
            self.lab_notice_badge.show()
        else:
            self.lab_notice_badge.setText("")
            self.lab_notice_badge.hide()

    def _check_notifications(self, force=False):
        """检查并拉取服务端通知；如果满足 24h 周期或 force 则执行网络请求。"""
        if not force and not self.notice_store.should_fetch(interval_seconds=86400):
            # 未满 24 小时，直接根据本地已缓存数据渲染红点
            self._refresh_notice_badge()
            return

        if self._notice_worker is not None and self._notice_worker.isRunning():
            return

        from core.config import APP_VERSION
        from pdk.notifications import resolve_pdk_server_endpoint
        base_url, app_id = resolve_pdk_server_endpoint()
        if pdk_auth is not None and pdk_auth.current_client() is not None:
            c = pdk_auth.current_client()
            base_url, app_id = c.base_url, c.app_id

        self._notice_worker = _NotificationWorker(base_url, app_id, APP_VERSION)
        self._notice_worker.fetched.connect(self._on_notifications_fetched)
        self._notice_worker.start()

    def _on_notifications_fetched(self, items):
        if isinstance(items, list):
            self.notice_store.save_fetched(items)
        self._refresh_notice_badge()

        # 强弹窗检查：若存在未读且 isPopup=1 的通知或升级，自动弹窗
        unreads = self.notice_store.get_unread_popups()
        if unreads:
            self.show_notifications_dialog(force=False)

    def show_notifications_dialog(self, force=False):
        """弹出通知与升级公告对话框。"""
        from ui.notification_dialog import NotificationDialog

        if force:
            from core.config import APP_VERSION
            from pdk.notifications import fetch_notifications, resolve_pdk_server_endpoint
            base_url, app_id = resolve_pdk_server_endpoint()
            if pdk_auth is not None and pdk_auth.current_client() is not None:
                c = pdk_auth.current_client()
                base_url, app_id = c.base_url, c.app_id
            items = fetch_notifications(base_url, app_id, APP_VERSION, timeout=4)
            if items:
                self.notice_store.save_fetched(items)

        dlg = NotificationDialog(self, self.notice_store, on_read_changed=self._refresh_notice_badge)
        dlg.exec_()
        self.notice_store.mark_all_as_read()
        self._refresh_notice_badge()

    def _request_logout(self):
        """优雅注销后返回登录窗口。"""
        self._begin_shutdown(return_to_login=True)

    # ------------------------------------------------------------ 会话校验
    def run_authorized(self, callback):
        """关键业务操作前重新向服务端确认会话，成功后在 UI 线程执行 callback。"""
        if self._shutdown_in_progress:
            return
        if self._authorized_callbacks:
            return
        self._authorized_callbacks.append(callback)
        self._show_session_error = True
        self.lab_account.setText("正在向服务器校验授权…")
        self.lab_account.setStyleSheet(
            theme.label_style(theme.FS_SMALL, theme.PRIMARY_HOVER))
        self._start_session_check()

    def _start_session_check(self):
        if self._shutdown_in_progress or pdk_auth is None:
            return
        worker = self._session_worker
        if worker is not None:
            try:
                if worker.isRunning():
                    return
            except RuntimeError:
                pass
        worker = _SessionVerifyWorker(self)
        worker.verified.connect(self._on_session_verified)
        worker.failed.connect(self._on_session_failed)
        worker.finished.connect(lambda w=worker: self._on_session_worker_finished(w))
        self._session_worker = worker
        worker.start()

    def _on_session_verified(self, result):
        if self._shutdown_in_progress:
            self._authorized_callbacks.clear()
            return
        self.lab_account.setText("当前账号：%s · %s" %
                                 (result.masked_phone, result.status))
        self.lab_account.setStyleSheet(
            theme.label_style(theme.FS_SMALL, theme.TEXT_MUTED))
        if self.host_panel.auth_panel is not None:
            self.host_panel.auth_panel.refresh_status()
        callbacks, self._authorized_callbacks = self._authorized_callbacks, []
        self._show_session_error = False
        for callback in callbacks:
            try:
                callback()
            except Exception:
                import traceback as _tb
                report_fatal("授权后业务操作", _tb.format_exc())

    def _on_session_failed(self, exc):
        if self._shutdown_in_progress:
            return
        callbacks, self._authorized_callbacks = self._authorized_callbacks, []
        show_error, self._show_session_error = self._show_session_error, False
        self.lab_account.setText("授权校验失败")
        self.lab_account.setStyleSheet(
            theme.label_style(theme.FS_SMALL, theme.AMBER))
        must_relogin = bool(getattr(exc, "code", 0) and
                            not getattr(exc, "retryable", False))
        if show_error or callbacks or must_relogin:
            QMessageBox.warning(
                self, "授权校验失败",
                pdk_auth.format_error(exc) if pdk_auth is not None else str(exc),
            )
        if must_relogin:
            self._begin_shutdown(return_to_login=True)

    def _on_session_worker_finished(self, worker):
        if self._session_worker is worker:
            self._session_worker = None
        worker.deleteLater()

    # ------------------------------------------------------------ 退出生命周期
    def _cleanup_runtime(self):
        self.timer.stop()
        self.auth_timer.stop()
        self.session_timer.stop()
        self._authorized_callbacks.clear()
        try:
            self.host_panel.shutdown()
        except Exception as exc:
            print(f"[退出] 停止摄像头探测失败: {exc}")
        try:
            self.host_stream.stop()
        except Exception as exc:
            print(f"[退出] 停止主播资源失败: {exc}")
        try:
            self.client_stream.stop()
        except Exception as exc:
            print(f"[退出] 停止观众资源失败: {exc}")

    def _begin_shutdown(self, return_to_login):
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True
        self._logout_requested = bool(return_to_login)
        self.btn_logout.setEnabled(False)
        self.btn_logout.setText("正在退出…")
        self.lab_account.setText("正在安全注销并释放音视频资源…")
        self._cleanup_runtime()

        worker = _LogoutWorker(self)
        worker.failed.connect(
            lambda exc: print("[PDK] 注销请求失败，本地会话已清理: %s" % exc))
        worker.finished.connect(self._finish_shutdown)
        self._logout_worker = worker
        worker.start()

    def _finish_shutdown(self):
        worker = self._logout_worker
        self._logout_worker = None
        if worker is not None:
            worker.deleteLater()
        self._shutdown_complete = True
        self.close()

    # ---------------------------------------------------------------- 页面导航
    def enter_host_mode(self):
        """进入主播模式：打开摄像头预览（不要求授权，推流时才校验），预览画面立即可见。"""
        self.stack.setCurrentIndex(1)
        try:
            self.host_panel.ensure_preview()
        except Exception:
            import traceback as _tb
            report_fatal("进入主播模式", _tb.format_exc())

    def enter_client_auto(self):
        self.stack.setCurrentIndex(2)
        self.client_stream.auto_find_and_connect()

    def return_home(self):
        """返回首页：停止推流与预览、释放摄像头与观众端资源。"""
        self.timer.stop()
        self.host_stream.stop_streaming()
        self.host_stream.stop()
        self.client_stream.stop()
        self.host_panel.reset_preview()
        self.client_panel.reset_preview()
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        if self._shutdown_complete:
            event.accept()
            return
        event.ignore()
        self._begin_shutdown(return_to_login=False)
