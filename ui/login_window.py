# -*- coding: utf-8 -*-
"""矩阵转发客户端的 PDK 登录 / 设备激活窗口（PyQt5 版）。

布局：左侧 400 渐变 banner + 右侧 580 操作区（登录、激活 tab + 版本号）。
风格：与矩阵转发主控台统一的深海蓝配色、圆角输入框、圆角按钮和 tab 下划线。
业务：PDK 公共配置 → 业务发现 → 登录 → 会话校验 → 资料 / 设备许可证，
      全部委托 `pdk.auth_service`，本模块不接触 Token 与加密细节。

窗口以 QDialog 形式使用：`exec_() == QDialog.Accepted` 表示登录成功，
main.py 据此决定是否进入主窗口。
"""
import os

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ui import theme
from ui.brand_banner import BrandBanner
from ui.icons import ICON_SIZE, icon_pixmap
from core.config import APP_VERSION
from core.credentials import save_credentials, load_credentials


# PDK 客户端依赖 requests + cryptography。缺任一依赖时**不能**让整个登录界面
# 崩掉：那样用户只看到闪退，无从定位。这里降级为「界面正常显示、点击登录时
# 给出明确的缺依赖提示」。
try:
    from pdk import auth_service as pdk_auth
    from pdk.pdk_client import PdkClientError

    PDK_IMPORT_ERROR = None
except Exception as _exc:                                   # pragma: no cover
    pdk_auth = None
    PDK_IMPORT_ERROR = _exc

    class PdkClientError(Exception):
        """占位类型：PDK 未就绪时让 isinstance 判断恒为 False。"""

        code = 0


class _FocusLineEdit(QLineEdit):
    """会广播焦点变化的输入框，用于驱动外层边框与图标同步变色。"""

    focusChanged = pyqtSignal(bool)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focusChanged.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusChanged.emit(False)


class IconField(QFrame):
    """「自绘图标 + 输入框」的输入行，聚焦时边框与图标一起变蓝。

    颜色联动是刻意的：只变边框的话，深色背景下焦点提示太弱。
    """

    def __init__(self, icon_key, placeholder, password=False, parent=None):
        super().__init__(parent)
        self.icon_key = icon_key
        self.setFixedHeight(50)
        self._apply_border(theme.BORDER)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self.icon = QLabel()
        self.icon.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.icon.setStyleSheet("background:transparent;border:none;")
        self._paint_icon(theme.TEXT_MUTED)
        lay.addWidget(self.icon)

        self.edit = _FocusLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFont(theme.font(theme.FS_BODY))
        if password:
            self.edit.setEchoMode(QLineEdit.Password)
        # 边框由外层 QFrame 负责，内部输入框保持透明无边框
        self.edit.setStyleSheet(
            f"background:transparent;border:none;padding:0;"
            f"color:{theme.TEXT};font-size:{theme.FS_BODY}pt;"
        )
        self.edit.focusChanged.connect(self._on_focus)
        lay.addWidget(self.edit, 1)

    def _apply_border(self, color):
        self.setStyleSheet(
            f"QFrame{{background-color:{theme.SURFACE_SOFT};"
            f"border:1px solid {color};border-radius:10px;}}"
        )

    def _paint_icon(self, color):
        ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1
        self.icon.setPixmap(icon_pixmap(self.icon_key, color, ratio=ratio or 1))

    def _on_focus(self, focused):
        self._apply_border(theme.BORDER_FOCUS if focused else theme.BORDER)
        self._paint_icon(theme.BORDER_FOCUS if focused else theme.TEXT_MUTED)

    # -- 便捷代理 --
    def text(self):
        return self.edit.text()

    def setText(self, value):
        self.edit.setText(value)


class TabBar(QWidget):
    """文字 tab + 跟随移动的下划线。

    激活态同时改「颜色 + 字重」，比只变颜色的层次更明确。
    """

    changed = pyqtSignal(str)

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self._buttons = {}
        self.active_key = tabs[0][0]

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for key, label in tabs:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            btn.setFixedHeight(43)
            btn.clicked.connect(lambda _c=False, k=key: self.set_active(k))
            lay.addWidget(btn)
            self._buttons[key] = btn
        lay.addStretch()

        # 下划线不进布局，直接以子控件形式绝对定位
        self.underline = QFrame(self)
        self.underline.setStyleSheet(
            f"background-color:{theme.PRIMARY_HOVER};border:none;border-radius:1px;"
        )
        self.underline.setFixedHeight(3)
        self._restyle()

    def set_active(self, key):
        if key not in self._buttons:
            return
        self.active_key = key
        self._restyle()
        self.changed.emit(key)

    def _restyle(self):
        for key, btn in self._buttons.items():
            on = key == self.active_key
            color = theme.PRIMARY_HOVER if on else theme.TEXT_MUTED
            btn.setFont(theme.font(theme.FS_H2, bold=on))
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;color:{color};"
                f"padding:10px 18px;font-size:{theme.FS_H2}pt;"
                f"font-weight:{'bold' if on else 'normal'};}}"
                f"QPushButton:hover{{color:{theme.PRIMARY_HOVER};}}"
            )
        self._place_underline()

    def _place_underline(self):
        """把下划线移到激活 tab 正下方，宽度贴合按钮。

        首次 show 前 Qt 还没完成布局计算，此时 geometry 宽度不可靠，因此
        resizeEvent / showEvent 都会再调一次，避免「启动时没有下划线、切一次
        tab 才出现」。
        """
        btn = self._buttons.get(self.active_key)
        if btn is None:
            return
        geo = btn.geometry()
        if geo.width() <= 1:
            return
        self.underline.setGeometry(geo.x(), self.height() - 3, geo.width(), 3)
        self.underline.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_underline()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._place_underline)


class AuthWorker(QThread):
    """在后台线程执行 PDK 认证，避免网络等待卡死 UI。

    ⚠️ 调用方必须持有本对象引用（例如 self._worker = worker）。QThread 被 GC
    回收会导致 C++ 侧线程对象悬空，进程直接崩溃 —— 本项目历史上就踩过这个坑
    （commit 54175b7「悬空 QThread 包装器」）。
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, phone, password, card_key, parent=None):
        super().__init__(parent)
        self.phone = phone
        self.password = password
        self.card_key = card_key

    def run(self):
        try:
            result = pdk_auth.authenticate(self.phone, self.password, self.card_key)
        except BaseException as exc:          # 任何异常都要回到 UI 线程展示
            self.failed.emit(exc)
            return
        self.succeeded.emit(result)


class LoginWindow(QDialog):
    """登录窗口。`exec_() == QDialog.Accepted` 表示认证通过。

    认证成功后的会话由 `pdk.auth_service` 以模块级单例持有，主窗口通过
    `pdk_auth.current_auth()` / `is_authenticated()` 读取，无需本窗口传递。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.auth_result = None
        self._worker = None            # 见 AuthWorker 的 GC 警告
        self._busy = False
        self._pending = {              # 待持久化的本次登录凭据（成功后才落盘）
            "phone": "", "password": "", "card_key": "",
        }

        self.setWindowTitle("智播豆 · 登录 v%s" % APP_VERSION)
        self.setFixedSize(980, 640)
        self.setStyleSheet(theme.app_qss())

        self._build()

    # ---------------------------------------------------------------- 布局
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        banner = BrandBanner(APP_VERSION)
        banner.setFixedWidth(400)
        root.addWidget(banner)

        right = QWidget()
        right.setStyleSheet(f"background-color:{theme.BG};")
        root.addWidget(right, 1)
        self._build_right(right)

    def _build_right(self, right):
        lay = QVBoxLayout(right)
        lay.setContentsMargins(48, 28, 48, 0)
        lay.setSpacing(0)

        # ----- 顶部欢迎语（三级层次：眉标 / 主标题 / 副标题） -----
        eyebrow = QLabel("PDK SECURE ACCESS")
        eyebrow.setFont(theme.font_en(9, bold=True))
        eyebrow.setStyleSheet(
            f"color:{theme.PRIMARY_HOVER};background:transparent;letter-spacing:1px;")
        lay.addWidget(eyebrow)
        lay.addSpacing(7)

        title = QLabel("欢迎使用智播豆")
        title.setFont(theme.font(theme.FS_H1, bold=True))
        title.setStyleSheet(theme.label_style(theme.FS_H1, theme.TEXT, bold=True))
        lay.addWidget(title)
        lay.addSpacing(8)

        subtitle = QLabel("登录矩阵转发工作台，管理推流与多端分发")
        subtitle.setFont(theme.font(theme.FS_CAPTION))
        subtitle.setStyleSheet(theme.label_style(theme.FS_CAPTION, theme.TEXT_MUTED))
        lay.addWidget(subtitle)
        lay.addSpacing(14)

        # ----- tab 行 + 分隔线 -----
        self.tabs = TabBar([("login", "登录"), ("active", "激活")])
        self.tabs.changed.connect(self._on_tab_changed)
        lay.addWidget(self.tabs)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color:{theme.BORDER};border:none;")
        lay.addWidget(divider)
        lay.addSpacing(20)

        # ----- 内容区（两个 tab 页叠放，切换时显隐） -----
        self.pages = {
            "login": self._build_login_page(),
            "active": self._build_active_page(),
        }
        for page in self.pages.values():
            lay.addWidget(page)
        lay.addStretch()

        # ----- 底部版本号 + 连接目标（便于现场发现连错服务） -----
        foot = QLabel(self._foot_text())
        foot.setAlignment(Qt.AlignCenter)
        foot.setFont(theme.font(theme.FS_SMALL))
        foot.setStyleSheet(theme.label_style(theme.FS_SMALL, theme.TEXT_FAINT))
        lay.addWidget(foot)
        lay.addSpacing(12)

        self._prefill_credentials()
        self._on_tab_changed("login")

    def _foot_text(self):
        base = "当前版本：%s" % APP_VERSION
        if pdk_auth is None:
            return base + "　|　PDK 组件未就绪"
        try:
            return base + "　|　" + pdk_auth.environment_hint()
        except Exception:
            return base

    def _build_login_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.login_phone = IconField("user", "请输入手机号")
        self.login_password = IconField("lock", "请输入密码", password=True)
        lay.addWidget(self.login_phone)
        lay.addSpacing(14)
        lay.addWidget(self.login_password)
        lay.addSpacing(10)

        # 状态提示行 + 换绑说明
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel("登录状态仅保留在本次运行中")
        self.hint.setFont(theme.font(theme.FS_SMALL))
        self.hint.setStyleSheet(theme.label_style(theme.FS_SMALL, theme.TEXT_MUTED))
        row.addWidget(self.hint)
        row.addStretch()

        rebind = QLabel("设备换绑请联系管理员")
        rebind.setFont(theme.font(theme.FS_SMALL, underline=True))
        rebind.setCursor(Qt.PointingHandCursor)
        rebind.setStyleSheet(
            f"color:{theme.PRIMARY_HOVER};background:transparent;"
            f"font-size:{theme.FS_SMALL}pt;text-decoration:underline;")
        rebind.mousePressEvent = lambda _e: QMessageBox.information(
            self, "提示", "请联系管理员解绑原设备许可证后再登录")
        row.addWidget(rebind)
        lay.addLayout(row)
        lay.addSpacing(12)

        self.btn_login = QPushButton("登录")
        self._style_primary(self.btn_login)
        self.btn_login.clicked.connect(self._do_login)
        lay.addWidget(self.btn_login)

        # 回车直接提交
        self.login_phone.edit.returnPressed.connect(self._do_login)
        self.login_password.edit.returnPressed.connect(self._do_login)
        return page

    def _build_active_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.act_phone = IconField("user", "请输入手机号")
        self.act_password = IconField("lock", "请输入密码", password=True)
        self.act_card = IconField("card", "请输入卡密", password=True)
        for i, field in enumerate((self.act_phone, self.act_password, self.act_card)):
            if i:
                lay.addSpacing(14)
            lay.addWidget(field)
        lay.addSpacing(10)

        tip = QLabel("卡密兑换成功后会自动登录并绑定当前设备")
        tip.setFont(theme.font(theme.FS_SMALL))
        tip.setStyleSheet(theme.label_style(theme.FS_SMALL, theme.TEXT_MUTED))
        lay.addWidget(tip)
        lay.addSpacing(12)

        self.btn_activate = QPushButton("立即兑换")
        self._style_primary(self.btn_activate)
        self.btn_activate.clicked.connect(self._do_activate)
        lay.addWidget(self.btn_activate)

        for field in (self.act_phone, self.act_password, self.act_card):
            field.edit.returnPressed.connect(self._do_activate)
        return page

    def _style_primary(self, btn):
        btn.setFixedHeight(48)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFont(theme.font(theme.FS_BODY + 1, bold=True))
        btn.setStyleSheet(
            f"QPushButton{{background-color:{theme.PRIMARY};color:#FFFFFF;"
            f"border:none;border-radius:12px;font-size:{theme.FS_BODY + 1}pt;"
            f"font-weight:bold;}}"
            f"QPushButton:hover{{background-color:{theme.PRIMARY_HOVER};}}"
            f"QPushButton:pressed{{background-color:{theme.shade(theme.PRIMARY, 0.88)};}}"
            f"QPushButton:disabled{{background-color:{theme.SURFACE_ALT};"
            f"color:{theme.TEXT_FAINT};}}"
        )

    def _on_tab_changed(self, key):
        for name, page in self.pages.items():
            page.setVisible(name == key)

    # ---------------------------------------------------------------- 交互
    def _do_login(self):
        phone = self.login_phone.text().strip()
        password = self.login_password.text()
        if not phone:
            self._warn("请输入手机号")
            return
        if not password:
            self._warn("请输入密码")
            return
        # 普通登录绝不隐式携带卡密。DEVICE_LICENSE 新设备需要激活时，服务端
        # 返回 40380，界面会切换到激活页由用户明确提交卡密。
        self._start_auth(phone, password)

    def _do_activate(self):
        phone = self.act_phone.text().strip()
        password = self.act_password.text()
        card = self.act_card.text().strip()
        if not phone:
            self._warn("请输入手机号")
            return
        if not password:
            self._warn("请输入密码")
            return
        if not card:
            self._warn("请输入卡密")
            return
        self._start_auth(phone, password, card)

    def _start_auth(self, phone, password, card_key=""):
        if self._busy:
            return
        # 记下本次认证参数，登录成功后再落盘；失败不保存
        self._pending = {
            "phone": phone, "password": password, "card_key": card_key,
        }
        if pdk_auth is None:
            QMessageBox.critical(
                self, "组件缺失",
                "PDK 授权组件不可用，无法登录。\n\n原因：%s\n\n"
                "请先安装依赖：pip install requests cryptography" % PDK_IMPORT_ERROR)
            return

        self._busy = True
        self._set_buttons_enabled(False)
        self.hint.setText("正在连接 PDK 授权服务器…")

        worker = AuthWorker(phone, password, card_key, parent=self)
        worker.succeeded.connect(self._on_auth_ok)
        worker.failed.connect(lambda exc, p=phone, pw=password: self._on_auth_fail(exc, p, pw))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        # 必须持引用，否则 QThread 被 GC 会导致进程崩溃
        self._worker = worker
        worker.start()

    def _set_buttons_enabled(self, enabled):
        self.btn_login.setEnabled(enabled)
        self.btn_activate.setEnabled(enabled)

    def _on_worker_finished(self, worker):
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()

    def _on_auth_ok(self, result):
        self._busy = False
        self._set_buttons_enabled(True)
        self.auth_result = result
        self._persist_credentials()
        self.hint.setText("PDK 会话已验证")
        QMessageBox.information(
            self, "提示", "登录成功\n%s\n正在进入主控台…" % result.display_detail())
        self.accept()

    def _persist_credentials(self):
        """登录成功后把本次凭据加密落盘，供下次自动回填（失败静默忽略）。"""
        creds = self._pending or {}
        phone = creds.get("phone", "")
        password = creds.get("password", "")
        card_key = creds.get("card_key", "")
        if phone and password:
            save_credentials(phone, password, card_key)

    def _prefill_credentials(self):
        """构造时回填已保存凭据（环境变量联调值优先于本地凭据）。

        仅在确有手机号时提示「已自动填入」，避免每次开屏都误导用户。
        """
        phone = os.getenv("PDK_PHONE") or ""
        password = os.getenv("PDK_PASSWORD") or ""
        card_key = os.getenv("PDK_CARD_KEY") or ""
        if not phone:
            try:
                creds = load_credentials() or {}
            except Exception:
                creds = {}
            phone = creds.get("phone", "")
            password = password or creds.get("password", "")
            card_key = card_key or creds.get("card_key", "")

        if not phone:
            return
        self.login_phone.setText(phone)
        if password:
            self.login_password.setText(password)
        self.act_phone.setText(phone)
        if password:
            self.act_password.setText(password)
        if card_key:
            self.act_card.setText(card_key)
        self.hint.setText("已自动填入上次登录账号，可直接登录")

    def _on_auth_fail(self, exc, phone, password):
        self._busy = False
        self._set_buttons_enabled(True)
        self.hint.setText("登录状态仅保留在本次运行中")
        QMessageBox.critical(self, "提示", "PDK 登录失败\n\n" + pdk_auth.format_error(exc))
        # 40380 = 需要卡密激活：自动切到激活页并回填，省掉重新输入
        if isinstance(exc, PdkClientError) and getattr(exc, "code", 0) == 40380:
            self.tabs.set_active("active")
            self.act_phone.setText(phone)
            self.act_password.setText(password)

    def _warn(self, msg):
        QMessageBox.warning(self, "提示", msg)

    def reject(self):
        if self._busy:
            self.hint.setText("认证请求正在处理中，请稍候…")
            return
        super().reject()

    def closeEvent(self, event):
        if self._busy:
            self.hint.setText("认证请求正在处理中，请稍候…")
            event.ignore()
            return
        event.accept()
