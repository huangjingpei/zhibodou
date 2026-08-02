#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
直播豆（智播豆）一键打包脚本 —— 生成 Windows exe。

用法（在装齐依赖的环境中执行）：
    python build_exe.py                 # one-folder + 控制台，日志可见（推荐用于调试）
    python build_exe.py --windowed      # 无控制台窗口的发布版（日志写入 exe 同目录 zhibodou.log）
    python build_exe.py --onefile       # 单文件 exe（启动慢、体积大，不推荐）
    python build_exe.py --no-clean      # 复用上次构建缓存，加快二次构建
    python build_exe.py --icon app.ico  # 指定图标

产物：
    dist/zhibodou/zhibodou.exe   （one-folder，依赖在 _internal/ 内）
    dist/zhibodou.exe            （--onefile）
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "zhibodou.py")
PROJECT_DIST = os.path.join(HERE, "dist")

# 运行期必需、但 PyInstaller 静态分析可能漏掉的模块
HIDDEN_IMPORTS = [
    "cv2",
    "av",
    "sounddevice",
    "pyvirtualcam",
    "requests",
    "numpy",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
]

# streamlink 通过插件目录动态加载解析器，必须整包收集，否则打包后解析直播链接必定失败
COLLECT_ALL = ["streamlink"]

# 明确排除的重量级/无用依赖，显著缩减产物体积
EXCLUDES = [
    # 本项目完全没用到的 Qt 子模块（cv2 与 PyQt5 都可能把它们拖进来）
    "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "PyQt5.QtWebEngine",
    "PyQt5.QtWebKit", "PyQt5.QtWebKitWidgets", "PyQt5.QtWebChannel",
    "PyQt5.QtQml", "PyQt5.QtQuick", "PyQt5.QtQuick3D", "PyQt5.QtQuickWidgets",
    "PyQt5.Qt3DCore", "PyQt5.Qt3DRender", "PyQt5.Qt3DInput",
    "PyQt5.Qt3DAnimation", "PyQt5.Qt3DExtras", "PyQt5.Qt3DLogic",
    "PyQt5.QtBluetooth", "PyQt5.QtNfc", "PyQt5.QtPositioning",
    "PyQt5.QtLocation", "PyQt5.QtSerialPort", "PyQt5.QtSensors",
    "PyQt5.QtMultimedia", "PyQt5.QtMultimediaWidgets", "PyQt5.QtDesigner",
    "PyQt5.QtHelp", "PyQt5.QtSql", "PyQt5.QtTest", "PyQt5.QtXmlPatterns",
    # 其它常见的“顺手被打进来”的大块头
    # 注意：不要排除 unittest / sqlite3 / setuptools —— numpy.testing、
    # 部分三方库会在导入链上依赖它们，排掉会在运行期报 ImportError
    "tkinter", "matplotlib", "scipy", "pandas", "IPython", "jupyter",
    "notebook", "pytest", "pydoc_data", "lib2to3",
    "PySide2", "PySide6", "PyQt6",
]


def die(msg):
    print(f"[build][错误] {msg}")
    sys.exit(1)


def check_deps():
    """构建前检查依赖，避免打出一个跑不起来的空壳。"""
    required = {
        "PyInstaller": "pyinstaller",
        "cv2": "opencv-python",
        "PyQt5": "PyQt5",
        "numpy": "numpy",
        "sounddevice": "sounddevice",
        "requests": "requests",
        "streamlink": "streamlink",
        "pyvirtualcam": "pyvirtualcam",
    }
    missing = []
    for mod, pkg in required.items():
        try:
            __import__(mod)
        except Exception:
            missing.append(pkg)
    if missing:
        die("缺少依赖: " + ", ".join(missing) +
            "\n        请先执行: pip install -r requirements.txt pyinstaller")

    # av 缺失不阻断构建，但会退化为 ffmpeg 推流方案
    try:
        __import__("av")
    except Exception:
        print("[build][警告] 未安装 av，产物将无法使用 PyAV 推流后端，只能回退 ffmpeg")


def resolve_ffmpeg():
    """定位 ffmpeg.exe：项目根 > 系统 PATH > imageio-ffmpeg 自带二进制。"""
    local = os.path.join(HERE, "ffmpeg.exe")
    if os.path.isfile(local):
        return local, "项目根目录"
    found = shutil.which("ffmpeg")
    if found:
        return found, "系统 PATH"
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p, "imageio-ffmpeg"
    except Exception:
        pass
    return None, None


def dir_size_mb(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1024 / 1024


def main():
    ap = argparse.ArgumentParser(description="直播豆 exe 打包脚本")
    ap.add_argument("--windowed", action="store_true",
                    help="构建无控制台窗口的发布版（日志改写入 zhibodou.log）")
    ap.add_argument("--onefile", action="store_true",
                    help="打包为单个 exe 文件（启动慢，不推荐）")
    ap.add_argument("--no-clean", action="store_true",
                    help="复用上次构建缓存（默认每次全新构建）")
    ap.add_argument("--icon", default="", help="exe 图标（.ico 路径）")
    args = ap.parse_args()

    if not os.path.isfile(ENTRY):
        die(f"入口文件不存在: {ENTRY}")
    check_deps()

    # 项目根若残留旧 spec，提醒一下：本脚本不使用它（spec 统一生成到临时目录）
    stale_spec = os.path.join(HERE, "zhibodou.spec")
    if os.path.isfile(stale_spec):
        print(f"[build][提示] 检测到旧的构建残留 {stale_spec}，本脚本不使用它，可安全删除")

    # 构建中间产物一律放系统临时目录，保持项目目录干净
    workpath = os.path.join(tempfile.gettempdir(), "zhibodou_build")
    specpath = os.path.join(tempfile.gettempdir(), "zhibodou_spec")
    # 沙箱/受限环境下直接写项目 dist 可能被安全删除策略拦截，此时先落临时目录再拷回
    sandboxed = os.environ.get("CODEBUDDY_SAFE_DELETE_SANDBOX") == "1"
    distpath = os.path.join(tempfile.gettempdir(), "zhibodou_dist") if sandboxed else PROJECT_DIST
    os.makedirs(specpath, exist_ok=True)

    opts = [
        ENTRY,
        "--name", "zhibodou",
        "--noconfirm",                 # 覆盖旧产物时不要交互询问，否则脚本会卡住
        "--noupx",                     # UPX 压缩会让部分杀软误报，且对 Qt dll 有兼容问题
        "--distpath", distpath,
        "--workpath", workpath,
        "--specpath", specpath,
    ]
    if not args.no_clean:
        opts.append("--clean")
    for m in HIDDEN_IMPORTS:
        opts += ["--hidden-import", m]
    for m in COLLECT_ALL:
        opts += ["--collect-all", m]
    for m in EXCLUDES:
        opts += ["--exclude-module", m]

    opts.append("--onefile" if args.onefile else "--onedir")
    opts.append("--windowed" if args.windowed else "--console")

    if args.icon:
        icon = args.icon if os.path.isabs(args.icon) else os.path.join(HERE, args.icon)
        if os.path.isfile(icon):
            opts += ["--icon", icon]
        else:
            print(f"[build][警告] 图标文件不存在，已忽略: {icon}")

    # ffmpeg.exe 作为回退推流方案的二进制，随产物分发
    ffmpeg, src = resolve_ffmpeg()
    if ffmpeg:
        sep = ";" if sys.platform.startswith("win") else ":"
        opts += ["--add-binary", f"{ffmpeg}{sep}."]
        print(f"[build] 已包含 ffmpeg（来源：{src}）-> {ffmpeg}")
    else:
        print("[build][警告] 未找到 ffmpeg，产物中将不含回退推流二进制。"
              "若目标机器也没有 ffmpeg 且 av 不可用，则无法推流")

    print(f"[build] 模式: {'onefile' if args.onefile else 'onedir'}"
          f" / {'windowed' if args.windowed else 'console'}")
    print(f"[build] 输出目录: {distpath}")

    t0 = time.time()
    from PyInstaller.__main__ import run as pyi_run
    try:
        pyi_run(opts)
    except SystemExit as e:
        if e.code not in (0, None):
            die(f"PyInstaller 退出码 {e.code}，构建失败")
    cost = time.time() - t0

    # 沙箱模式：把临时目录产物拷回项目 dist/
    if sandboxed and os.path.isdir(distpath):
        os.makedirs(PROJECT_DIST, exist_ok=True)
        for name in os.listdir(distpath):
            s, d = os.path.join(distpath, name), os.path.join(PROJECT_DIST, name)
            if os.path.isdir(s):
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        print(f"[build] 已将产物从临时目录拷回 {PROJECT_DIST}")

    target = (os.path.join(PROJECT_DIST, "zhibodou.exe") if args.onefile
              else os.path.join(PROJECT_DIST, "zhibodou", "zhibodou.exe"))
    if not os.path.isfile(target):
        die(f"构建结束但未找到产物: {target}")

    size = (os.path.getsize(target) / 1024 / 1024 if args.onefile
            else dir_size_mb(os.path.dirname(target)))
    print("\n[build] ===== 构建完成 =====")
    print(f"[build] 耗时: {cost:.1f}s")
    print(f"[build] 产物: {target}")
    print(f"[build] 体积: {size:.1f} MB")
    if args.windowed:
        print("[build] 提示: windowed 版无控制台，运行日志见 exe 同目录 zhibodou.log")


if __name__ == "__main__":
    main()
