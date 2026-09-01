# -*- coding: utf-8 -*-
"""授权面板：机器码复制、激活码校验、授权状态刷新。

被主播页左侧控制区嵌入（auth_frame）。它只管授权这一块 UI：通过 phone_getter
拿到首页填写的手机号用于激活，通过 on_state 回调把「是否授权」回传给主播页
（决定是否允许开始推流）。
"""
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QFrame, QTextEdit
from licensing.auth import (get_machine_code, verify_and_save_activate_code, get_auth_info)
from core.config import DAY_SEC
from ui.widgets import CountDownDialog
from ui.panels.base import Panel


class AuthPanel(Panel):
    def __init__(self, win, phone_getter, on_state=None):
        super().__init__(win)
        self.phone_getter = phone_getter   # () -> 当前手机号字符串（来自首页）
        self.on_state = on_state           # (auth_ok: bool) -> None

    def build(self, parent):
        self.auth_frame = QFrame(parent)
        auth_lay = QVBoxLayout(self.auth_frame)
        self.lab_auth_status = QLabel("状态: 未激活")
        self.lab_auth_status.setWordWrap(True)
        self.lab_auth_status.setStyleSheet("font-size:13px;")
        self.lab_mc = QLabel(f"机器码: {get_machine_code()}")
        self.lab_mc.setStyleSheet("font-size:12px;color:#8899bb;")
        btn_copy_mc = QPushButton("复制机器码")
        btn_copy_mc.clicked.connect(self.copy_machine_code)
        self.license_edit = QTextEdit()
        self.license_edit.setFixedHeight(35)
        self.license_edit.setPlaceholderText("请输入激活码")
        btn_act = QPushButton("激活授权")
        btn_act.clicked.connect(self.do_activate)
        auth_lay.addWidget(self.lab_auth_status)
        auth_lay.addWidget(self.lab_mc)
        auth_lay.addWidget(btn_copy_mc)
        auth_lay.addWidget(self.license_edit)
        auth_lay.addWidget(btn_act)
        return self.auth_frame

    def copy_machine_code(self):
        mc = get_machine_code()
        QApplication.clipboard().setText(mc)
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self.auth_frame, "已复制", "机器码已复制到剪贴板!")

    def do_activate(self):
        from PyQt5.QtWidgets import QMessageBox
        try:
            phone = self.phone_getter().strip()
            code = self.license_edit.toPlainText().strip()
            if len(phone) != 11 or not phone.isdigit():
                QMessageBox.warning(self.auth_frame, "错误", "手机号必须是11位数字!")
                return
            if not code:
                QMessageBox.warning(self.auth_frame, "错误", "激活码不能为空!")
                return
            ok, msg = verify_and_save_activate_code(code, phone)
            if ok:
                CountDownDialog().exec_()
                self.refresh_status()
                QMessageBox.information(self.auth_frame, "成功", "激活成功!")
            else:
                QMessageBox.warning(self.auth_frame, "失败", msg)
        except Exception as e:
            QMessageBox.critical(self.auth_frame, "错误", f"操作失败: {str(e)}")

    def refresh_status(self):
        """刷新授权状态文案；并把是否授权通过 on_state 回传给主播页。"""
        auth_ok, remain_sec, total_days, max_client = get_auth_info()
        push_backend = self.win.host_stream.push_backend or "未启动"
        if auth_ok:
            days = remain_sec // DAY_SEC
            rem = remain_sec % DAY_SEC
            hours = rem // 3600
            rem %= 3600
            mins = rem // 60
            secs = rem % 60
            self.lab_auth_status.setText(
                f"状态: 已激活 | 剩余: {days}天 {hours:02d}时 {mins:02d}分 {secs:02d}秒\n推流后端: {push_backend}"
            )
        else:
            self.lab_auth_status.setText("状态: 未激活")
        if self.on_state:
            self.on_state(auth_ok)
