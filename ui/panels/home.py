# -*- coding: utf-8 -*-
"""首页面板：标题、使用须知、当前登录账号、协议勾选、进入主播/观众模式入口。

只管首页自己的控件与交互；点击「进入主播/观众模式」交给 MainWin 做页面导航。
手机号/密码已在登录窗口（PDK）采集，这里只展示已登录账号，不再单独输入。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QFrame,
)
from ui import theme
from ui.panels.base import Panel

try:
    from pdk import auth_service as pdk_auth
except Exception:  # pragma: no cover
    pdk_auth = None


class HomePanel(Panel):
    def build(self, parent):
        home = QWidget(parent)
        page_lay = QVBoxLayout(home)
        page_lay.setContentsMargins(40, 28, 40, 28)

        content = QWidget()
        content.setMaximumWidth(940)
        h_lay = QVBoxLayout(content)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(16)
        page_lay.addStretch(1)
        page_lay.addWidget(content, alignment=Qt.AlignHCenter)
        page_lay.addStretch(1)

        hero = QFrame()
        hero.setProperty("card", True)
        hero_lay = QVBoxLayout(hero)
        hero_lay.setContentsMargins(28, 22, 28, 22)
        hero_lay.setSpacing(8)

        lab_title = QLabel("智播豆")
        lab_title.setAlignment(Qt.AlignCenter)
        lab_title.setFont(theme.font(theme.FS_DISPLAY, bold=True))
        lab_title.setStyleSheet(theme.label_style(theme.FS_DISPLAY, theme.CYAN, bold=True))
        hero_lay.addWidget(lab_title)

        lab_subtitle = QLabel("矩阵转发 · 高清直播推流系统")
        lab_subtitle.setAlignment(Qt.AlignCenter)
        lab_subtitle.setFont(theme.font(theme.FS_H2))
        lab_subtitle.setStyleSheet(theme.label_style(theme.FS_H2, theme.TEXT_MUTED))
        hero_lay.addWidget(lab_subtitle)

        # 当前登录账号（只读，来自 PDK 会话）
        self.lab_account = QLabel("当前账号：未登录")
        self.lab_account.setAlignment(Qt.AlignCenter)
        self.lab_account.setFont(theme.font(theme.FS_CAPTION))
        self.lab_account.setStyleSheet(theme.label_style(theme.FS_CAPTION, theme.TEXT_SOFT))
        hero_lay.addWidget(self.lab_account)
        self._refresh_account()
        h_lay.addWidget(hero)

        body = QHBoxLayout()
        body.setSpacing(16)

        notice_card = QFrame()
        notice_card.setProperty("card", True)
        notice_lay = QVBoxLayout(notice_card)
        notice_lay.setContentsMargins(24, 20, 24, 20)
        notice_lay.setSpacing(12)
        notice_title = QLabel("使用须知")
        notice_title.setFont(theme.font(theme.FS_H2, bold=True))
        notice_title.setStyleSheet(theme.section_title_style())
        notice_lay.addWidget(notice_title)
        notice_text = """1. 本软件为音视频推流工具，仅供合法用途使用
2. 用户须遵守相关法律法规及平台政策
3. 软件授权一经售出，概不退款
4. 本软件不保证任何直播收益或效果
5. 使用本软件即表示同意以上条款"""
        lab_notice = QLabel(notice_text)
        lab_notice.setWordWrap(True)
        lab_notice.setFont(theme.font(theme.FS_BODY))
        lab_notice.setStyleSheet(theme.label_style(theme.FS_BODY, theme.TEXT_MUTED))
        notice_lay.addWidget(lab_notice)
        notice_lay.addStretch(1)
        body.addWidget(notice_card, 3)

        action_card = QFrame()
        action_card.setProperty("card", True)
        action_lay = QVBoxLayout(action_card)
        action_lay.setContentsMargins(24, 20, 24, 20)
        action_lay.setSpacing(14)
        action_title = QLabel("选择工作模式")
        action_title.setFont(theme.font(theme.FS_H2, bold=True))
        action_title.setStyleSheet(theme.section_title_style())
        action_lay.addWidget(action_title)

        action_tip = QLabel("确认使用条款后，选择当前电脑承担的直播角色。")
        action_tip.setWordWrap(True)
        action_tip.setFont(theme.font(theme.FS_SMALL))
        action_tip.setStyleSheet(theme.caption_style())
        action_lay.addWidget(action_tip)

        self.check_agree = QCheckBox("我已阅读并同意以上所有条款")
        self.check_agree.setFont(theme.font(theme.FS_SMALL))
        self.check_agree.stateChanged.connect(self.agree_state_change)
        action_lay.addWidget(self.check_agree)

        self.btn_host = QPushButton("进入主播模式")
        self.btn_client = QPushButton("进入观众模式")
        for btn in [self.btn_host, self.btn_client]:
            btn.setMinimumHeight(48)
            btn.setFont(theme.font(theme.FS_BODY + 1, bold=True))
            btn.setEnabled(False)
        self.btn_host.setProperty("accent", True)
        self.btn_client.setProperty("ghost", True)
        self.btn_host.clicked.connect(self.win.enter_host_mode)
        self.btn_client.clicked.connect(self.win.enter_client_auto)
        action_lay.addWidget(self.btn_host)
        action_lay.addWidget(self.btn_client)
        action_lay.addStretch(1)
        body.addWidget(action_card, 2)
        h_lay.addLayout(body)
        return home

    def _refresh_account(self):
        if pdk_auth is not None:
            result = pdk_auth.current_auth()
            if result is not None:
                self.lab_account.setText("当前账号：%s" % result.masked_phone)
                return
        self.lab_account.setText("当前账号：未登录")

    def agree_state_change(self):
        checked = self.check_agree.isChecked()
        self.btn_host.setEnabled(checked)
        self.btn_client.setEnabled(checked)
