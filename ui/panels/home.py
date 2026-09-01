# -*- coding: utf-8 -*-
"""首页面板：标题、使用须知、手机号输入、协议勾选、进入主播/观众模式入口。

只管首页自己的控件与交互；点击「进入主播/观众模式」交给 MainWin 做页面导航。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QScrollArea, QLineEdit, QCheckBox,
)
from licensing.auth import load_phone_config, save_phone_config

from ui.panels.base import Panel


class HomePanel(Panel):
    def build(self, parent):
        home = QWidget(parent)
        h_lay = QVBoxLayout(home)
        h_lay.setContentsMargins(50, 30, 50, 30)
        h_lay.setSpacing(20)

        lab_title = QLabel("智播豆")
        lab_title.setAlignment(Qt.AlignCenter)
        lab_title.setStyleSheet("font-size:32px;color:#00ccff;font-weight:bold;")
        h_lay.addWidget(lab_title)

        lab_subtitle = QLabel("高清直播推流系统")
        lab_subtitle.setAlignment(Qt.AlignCenter)
        lab_subtitle.setStyleSheet("font-size:16px;color:#8899bb;")
        h_lay.addWidget(lab_subtitle)

        h_lay.addSpacing(10)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_lay = QVBoxLayout(scroll_content)
        notice_text = """使用须知:
1. 本软件为音视频推流工具，仅供合法用途使用
2. 用户须遵守相关法律法规及平台政策
3. 软件授权一经售出，概不退款
4. 本软件不保证任何直播收益或效果
5. 使用本软件即表示同意以上条款"""
        lab_notice = QLabel(notice_text)
        lab_notice.setWordWrap(True)
        lab_notice.setStyleSheet("color:#bbbbbb;font-size:13px;line-height:1.8;")
        scroll_lay.addWidget(lab_notice)
        scroll_area.setWidget(scroll_content)
        scroll_area.setFixedHeight(180)
        h_lay.addWidget(scroll_area)

        phone_lay = QHBoxLayout()
        phone_lay.setSpacing(10)
        lab_phone_tip = QLabel("手机号码:")
        lab_phone_tip.setFixedWidth(100)
        lab_phone_tip.setStyleSheet("color:#00ccff;font-size:14px;")
        self.edit_phone = QLineEdit()
        self.edit_phone.setPlaceholderText("请输入11位手机号码")
        self.edit_phone.setText(self.win.local_phone)
        self.edit_phone.setStyleSheet("font-size:14px;")
        self.edit_phone.editingFinished.connect(self.on_phone_input_done)
        phone_lay.addWidget(lab_phone_tip)
        phone_lay.addWidget(self.edit_phone)
        h_lay.addLayout(phone_lay)

        self.check_agree = QCheckBox("我已阅读并同意以上所有条款")
        self.check_agree.setStyleSheet("font-size:13px;color:#e6edf3;")
        self.check_agree.stateChanged.connect(self.agree_state_change)
        h_lay.addWidget(self.check_agree, alignment=Qt.AlignCenter)

        h_lay.addSpacing(20)
        self.btn_host = QPushButton("进入主播模式")
        self.btn_client = QPushButton("进入观众模式")
        for btn in [self.btn_host, self.btn_client]:
            btn.setFixedSize(220, 50)
            btn.setStyleSheet("font-size:16px;font-weight:bold;")
            btn.setEnabled(False)
        self.btn_host.clicked.connect(self.win.enter_host_mode)
        self.btn_client.clicked.connect(self.win.enter_client_auto)
        h_lay.addWidget(self.btn_host, alignment=Qt.AlignCenter)
        h_lay.addWidget(self.btn_client, alignment=Qt.AlignCenter)
        h_lay.addStretch()
        return home

    def on_phone_input_done(self):
        phone = self.edit_phone.text().strip()
        save_phone_config(phone)
        self.win.local_phone = phone

    def agree_state_change(self):
        checked = self.check_agree.isChecked()
        self.btn_host.setEnabled(checked)
        self.btn_client.setEnabled(checked)
