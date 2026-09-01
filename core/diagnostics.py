# -*- coding: utf-8 -*-
"""崩溃诊断。

PyQt5 在槽函数 / QTimer 回调里出现未捕获异常时会直接 abort 进程，表现为
"点一下按钮软件就消失，没有弹窗也没有日志"。abort 无法阻止，但 PyQt5 在
abort 前会先走 sys.excepthook，因此这里挂钩子把现场落盘，保证有据可查。
"""
import os
import sys
import time

from PyQt5.QtWidgets import QMessageBox

from core.runtime import app_dir


def report_fatal(stage, exc_text):
    """启动阶段的致命错误：写日志 + 尽力弹窗，避免打包后“双击没反应”。"""
    print(f"[FATAL] {stage} 失败:\n{exc_text}")
    try:
        with open(os.path.join(app_dir(), "crash.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + f" [{stage}]\n" + exc_text + "\n\n")
    except Exception:
        pass
    try:
        QMessageBox.critical(None, "启动失败",
                             f"{stage} 失败，详情已写入 crash.log：\n\n" + exc_text[-1500:])
    except Exception:
        pass


def install_excepthook():
    """PyQt5 对槽函数内未捕获的 Python 异常会直接 qFatal/abort 整个进程——
    表现为"点一下按钮就闪退，没有弹窗也没有日志"。abort 无法阻止，但 PyQt5 在
    abort 前会先走 sys.excepthook，因此这里挂钩子把现场落盘，保证有据可查。"""
    import traceback as _tb

    _prev = sys.excepthook

    def _hook(etype, value, tb):
        try:
            text = "".join(_tb.format_exception(etype, value, tb))
            with open(os.path.join(app_dir(), "crash.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " [未捕获异常]\n" + text + "\n\n")
            print("[FATAL] 未捕获异常:\n" + text)
        except Exception:
            pass
        try:
            _prev(etype, value, tb)
        except Exception:
            pass

    sys.excepthook = _hook
