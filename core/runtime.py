# -*- coding: utf-8 -*-
"""运行时环境兜底。

本模块必须在任何 print / 任何重量级 import 之前被导入，它负责三件事：
  1. 打包成 --windowed 后 sys.stdout/stderr 为 None，直接 print 会抛
     AttributeError 崩进程 —— 这里重定向到 exe 同目录的 zhibodou.log；
  2. 探测 PyAV 是否可用（决定推流后端），失败时打印原因而不是静默退化；
  3. Windows 单例互斥锁，避免重复启动（--probe-cam 子进程必须跳过）。

依赖方向：本模块不 import 项目内任何其他模块，是最底层。
"""
import os
import sys
import subprocess
import time

# 项目根目录（core/ 的上一级）：拆分后不能再靠 __file__ 定位脚本目录
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 打包运行期兜底（必须在任何 print 之前完成）
# ============================================================
IS_FROZEN = getattr(sys, "frozen", False)

def app_dir():
    """程序所在目录：打包后为 exe 目录，开发时为脚本目录。"""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return _PACKAGE_ROOT

def _init_frozen_stdio():
    """PyInstaller --windowed 下 sys.stdout/stderr 为 None，任何 print() 都会抛
    AttributeError 直接崩溃。这里把标准输出重定向到 exe 同目录的 zhibodou.log，
    既避免崩溃，也让无控制台的发布版仍可排查问题。"""
    class _NullWriter:
        def write(self, *a, **kw): return 0
        def flush(self): pass
        def isatty(self): return False
    # 分辨率探测 worker 子进程不写日志文件（避免与主进程争抢），但仍需保证
    # stdout/stderr 非 None，否则 windowed 模式下任何 print 都会抛异常。
    if "--probe-cam" in sys.argv:
        if sys.stdout is None:
            sys.stdout = _NullWriter()
        if sys.stderr is None:
            sys.stderr = _NullWriter()
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_path = os.path.join(app_dir(), "zhibodou.log")
        fp = open(log_path, "a", encoding="utf-8", buffering=1, errors="replace")
        fp.write("\n===== 启动 %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        fp = _NullWriter()
    if sys.stdout is None:
        sys.stdout = fp
    if sys.stderr is None:
        sys.stderr = fp

_init_frozen_stdio()

# 打包成 windowed 版后，子进程（ffmpeg 等）默认会弹出一个黑色控制台窗口，
# 用 CREATE_NO_WINDOW 抑制。非 Windows 平台为 0，不影响行为。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# PyAV 为可选依赖：存在时优先用纯 Python 方式采集 + 编码 + 推流 RTMP
try:
    import av
    HAVE_AV = True
except Exception as _av_err:
    av = None
    HAVE_AV = False
    # 之前这里静默失败，导致运行时"凭空"退化到 ffmpeg 后端且难以排查。
    # 现在把原因打印出来，便于定位（常见于打包后 PyAV 动态库未随 exe 分发）。
    print(f"[警告] PyAV 导入失败（将回退 ffmpeg 推流后端）: {_av_err}")

# ============================================================
# 单例检测、工具函数、授权等
# ============================================================
# 注意：分辨率探测 worker 是主程序自调用的子进程，必须跳过单例检测，
# 否则它会撞上主进程持有的 mutex，弹出「程序已经在运行中」并卡死在模态框上。
if "--probe-cam" not in sys.argv:
    try:
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, 1, "Global\\ZhiBoDou_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:
            ctypes.windll.user32.MessageBoxW(0, "程序已经在运行中", "提示", 0)
            sys.exit(0)
    except:
        pass

# ------------------------------------------------------------
# 主入口脚本定位（worker 子进程自调用时使用）
#
# 拆分为包之后 __file__ 指向的是包内某个模块（如 capture\resolution.py），
# 不再是入口脚本。分辨率探测 worker 需要以「python <入口> --probe-cam」方式
# 自调用，因此这里统一提供入口路径：打包后是 exe 自身，开发时是 main.py。
# ------------------------------------------------------------
def entry_script():
    """返回主入口脚本的绝对路径。"""
    if IS_FROZEN:
        return sys.executable
    return os.path.join(_PACKAGE_ROOT, "main.py")
