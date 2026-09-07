# -*- coding: utf-8 -*-
"""授权面板：展示 PDK 会话状态，提供账户资料查看。

授权门禁已从本地「机器码 + 激活码」切换到 PDK 会话：是否允许推流由
`pdk.auth_service.is_authenticated()` 决定。本面板只展示当前会话的脱敏信息，
不接触 Token、设备 ID 等敏感字段。

账户资料与设备许可证状态以 PyQt5 面板形式嵌入主播页左侧控制区。
"""
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QPushButton, QMessageBox,
)
from ui import theme
from ui.panels.base import Panel

try:
    from pdk import auth_service as pdk_auth
except Exception:  # pragma: no cover
    pdk_auth = None


class AuthPanel(Panel):
    def __init__(self, win, on_state=None):
        super().__init__(win)
        self.on_state = on_state       # (auth_ok: bool) -> None，驱动「开始直播推流」可用态

    def build(self, parent):
        self.auth_frame = QFrame(parent)
        self.auth_frame.setProperty("card", True)
        auth_lay = QVBoxLayout(self.auth_frame)
        auth_lay.setContentsMargins(14, 14, 14, 14)
        auth_lay.setSpacing(12)

        title = QLabel("账户与授权")
        title.setFont(theme.font(theme.FS_H2, bold=True))
        title.setStyleSheet(theme.section_title_style())
        auth_lay.addWidget(title)

        self.lab_status = QLabel("状态: 未登录")
        self.lab_status.setWordWrap(True)
        self.lab_status.setFont(theme.font(theme.FS_CAPTION))
        self.lab_status.setStyleSheet(theme.label_style(theme.FS_CAPTION, theme.TEXT_SOFT))
        auth_lay.addWidget(self.lab_status)

        self.btn_profile = QPushButton("查看账户资料")
        self.btn_profile.setProperty("ghost", True)
        self.btn_profile.setFixedHeight(36)
        self.btn_profile.clicked.connect(self.show_profile)
        auth_lay.addWidget(self.btn_profile)

        auth_lay.addStretch(1)

        # 进入主窗口时 PDK 必然已登录，这里先刷一次保证状态文案正确
        self.refresh_status()
        return self.auth_frame

    def show_profile(self):
        if pdk_auth is None:
            QMessageBox.information(self.auth_frame, "PDK 账户", "PDK 授权组件未就绪")
            return
        result = pdk_auth.current_auth()
        if result is None:
            QMessageBox.warning(self.auth_frame, "PDK 账户", "当前没有有效 PDK 会话，请重新登录")
            return
        QMessageBox.information(
            self.auth_frame, "PDK 账户资料",
            "手机号：%s\n业务：%s\n授权模式：%s\n状态：%s\n媒体服务：%s\n剩余次数：%s" % (
                result.masked_phone,
                result.business.get("bizCode") or result.session.get("bizCode") or "-",
                result.authorization_mode or "-",
                result.status,
                result.live_media.get("mediaServerAddress") or "-",
                result.remaining_calls,
            ),
        )

    def refresh_status(self):
        """刷新授权状态文案，并把是否授权通过 on_state 回传给主播页。"""
        auth_ok = bool(pdk_auth and pdk_auth.is_authenticated())
        if auth_ok:
            result = pdk_auth.current_auth()
            detail = result.display_detail() if result else ""
            media = ""
            if result and result.live_media.get("mediaServerAddress"):
                media = "\n媒体: %s" % result.live_media.get("mediaServerAddress")
            self.lab_status.setText("状态: 已授权\n%s%s" % (detail, media))
        else:
            self.lab_status.setText("状态: 未授权")
        if self.on_state:
            self.on_state(auth_ok)
