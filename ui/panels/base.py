# -*- coding: utf-8 -*-
"""面板基类：所有 UI 面板共享主窗口引用。

面板只负责自己那一块界面的「控件创建 + 事件处理」，不关心页面导航与生命周期
（那些由 ui.main_window.MainWin 编排）。需要访问跨面板的共享状态时统一走 self.win。
"""
from PyQt5.QtWidgets import QWidget


class Panel:
    def __init__(self, win):
        self.win = win  # MainWin 实例，提供 host_stream / client_stream / timer / stack 等共享对象

    def build(self, parent):
        """构建本面板对应的页面控件，返回最外层 QWidget。子类必须实现。"""
        raise NotImplementedError
