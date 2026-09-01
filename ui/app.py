# -*- coding: utf-8 -*-
"""QApplication 子类：捕获 Qt 事件循环中的未捕获异常。

默认 PyQt5 在槽函数里抛异常会直接 abort 进程，表现为"点了就消失、没有任何
提示"。重写 notify 捕获后写日志 + 弹窗，让问题可见。
"""
import os
import time

from PyQt5.QtWidgets import QApplication, QMessageBox

from core.runtime import app_dir


class SafeApplication(QApplication):
    """捕获 Qt 事件循环中所有未处理的 Python 异常，避免进程静默崩溃退出。

    默认情况下，PyQt5 在槽函数 / QTimer 回调里抛出未捕获异常会直接 abort 进程，
    表现为“程序点了就消失、没有任何提示”。重写 notify 捕获异常后弹窗 + 写日志。
    """
    _crashed = False

    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception:
            import traceback as _tb
            tb_text = _tb.format_exc()
            print("[FATAL] 未捕获异常（已记录到 crash.log）:\n" + tb_text)
            try:
                _log = os.path.join(app_dir(), "crash.log")
                with open(_log, "a", encoding="utf-8") as _f:
                    _f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + tb_text + "\n\n")
            except Exception:
                pass
            if not SafeApplication._crashed:
                SafeApplication._crashed = True
                try:
                    QMessageBox.critical(None, "程序异常", "发生未捕获异常，已记录到 crash.log：\n\n" + tb_text[-1500:])
                except Exception:
                    pass
            return False
