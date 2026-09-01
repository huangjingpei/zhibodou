# -*- coding: utf-8 -*-
"""智播豆 主入口。

启动分三条路径：
  1) 带 --probe-cam 参数：作为分辨率探测 worker 子进程运行，只探测、写结果
     文件、立即退出，**不导入任何 Qt 模块**（探测可能因驱动问题崩在 C 层，
     导入越少越快退出，崩了也不影响主进程）；
  2) 带 --selfcheck 参数：逐个 import 项目全部模块并打印 JSON 结果，用于验证
     打包产物是否完整，不启动界面；
  3) 正常启动：创建 Qt 应用并打开主窗口。

模块划分见各包的 __init__.py 说明。
"""
import os
import sys

# 必须在任何 print / 任何重量级 import 之前导入：负责 windowed 模式 stdio
# 兜底、PyAV 可用性探测、单例互斥锁。
from core.runtime import IS_FROZEN  # noqa: F401  （导入即完成兜底）
from core.config import PROBE_ARG, SELFCHECK_ARG


def _run_probe_worker():
    """分辨率探测 worker 分支：探测摄像头支持的分辨率并写入指定文件。"""
    from capture.resolution import run_probe_worker

    i = sys.argv.index(PROBE_ARG)
    out = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
    run_probe_worker(out)
    return 0   # run_probe_worker 内部已 os._exit，此行仅作兜底


def _run_selfcheck():
    """打包自检：逐个 import 项目全部模块，JSON 输出成败，不启动界面。

    用途：PyInstaller 只把「静态分析能追踪到」的模块打进 PYZ 归档。拆包后模块
    数量变多，一旦某个模块将来改成运行期动态导入，就会在打包版里报 ImportError
    而开发环境毫无症状。打包后跑一次 `zhibodou.exe --selfcheck` 即可暴露。
    """
    import json

    from core.config import PROJECT_MODULES

    failed = []
    for name in PROJECT_MODULES:
        try:
            __import__(name)
        except Exception as e:
            failed.append({"module": name, "error": f"{type(e).__name__}: {e}"})

    print(json.dumps({
        "frozen": IS_FROZEN,
        "python": sys.version.split()[0],
        "total": len(PROJECT_MODULES),
        "ok": len(PROJECT_MODULES) - len(failed),
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def main():
    if PROBE_ARG in sys.argv:
        return _run_probe_worker()
    if SELFCHECK_ARG in sys.argv:
        return _run_selfcheck()

    import traceback

    from core.diagnostics import install_excepthook, report_fatal
    from ui.app import SafeApplication
    from ui.main_window import MainWin

    install_excepthook()
    app = SafeApplication(sys.argv)
    try:
        win = MainWin()
        win.show()
    except Exception:
        # 主窗口构造期的异常不在 Qt 事件循环内，SafeApplication.notify 兜不住
        report_fatal("主窗口初始化", traceback.format_exc())
        return 1
    return app.exec_()


if __name__ == "__main__":
    # 打包后若使用 multiprocessing，子进程会重新执行入口脚本导致无限开窗
    import multiprocessing

    multiprocessing.freeze_support()

    # 保证包可导入：打包后 sys.path 已包含程序目录，开发时以脚本目录为准
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    sys.exit(main())
