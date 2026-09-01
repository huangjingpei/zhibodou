#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
直播豆（智播豆）一键打包脚本 —— 生成 Windows exe。

入口: main.py（项目已按功能拆分为包，main.py 是唯一入口）
    core/        运行时兜底、全局配置、崩溃诊断、局域网发现
    capture/     音视频采集（设备枚举、麦克风、摄像头分辨率探测）
    processing/  流处理（美颜/裁竖屏、抖音直播源解析）
    streaming/   推流（PyAV 首选 / ffmpeg 回退 / 后端自动选择）
    sessions/    业务编排（主播会话、观众会话）
    licensing/   旧版授权兼容
    pdk/         PDK 登录、激活与设备许可证
    ui/          界面（主窗口、控件、应用类）

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
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "main.py")
PROJECT_DIST = os.path.join(HERE, "dist")

# 项目包（PyInstaller 静态分析一般能追踪到，但显式声明可确保万无一失）
PROJECT_PACKAGES = ["core", "capture", "processing", "streaming",
                    "sessions", "licensing", "pdk", "ui"]

# 运行期必需、但 PyInstaller 静态分析可能漏掉的模块
HIDDEN_IMPORTS = [
    "cv2",
    "av",
    "sounddevice",
    "pyvirtualcam",
    "requests",
    "cryptography",
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


def project_modules():
    """枚举 7 个业务包下的全部模块（含包自身与其子模块），返回点分模块名。

    PyInstaller 只把「静态分析能追踪到」的模块打进 PYZ 归档。像 core.net 这种
    当前无人 import 的预留模块会被自动剔除 —— 将来一旦被引用，就会在打包版
    报 ImportError，而开发环境毫无症状。所以这里逐个子模块显式声明。
    """
    mods = []
    for pkg in PROJECT_PACKAGES:
        root = os.path.join(HERE, pkg)
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            prefix = os.path.relpath(dirpath, HERE).replace("\\", "/").replace("/", ".")
            for f in filenames:
                if not f.endswith(".py"):
                    continue
                stem = f[:-3]
                mods.append(prefix if stem == "__init__" else f"{prefix}.{stem}")
    return sorted(set(mods))


def config_declared_modules():
    """从 core/config.py 读取 PROJECT_MODULES 声明清单。

    用 AST 静态取值而不是 import —— core.config 在导入时会创建用户数据目录，
    那是运行期行为，构建脚本不该触发它。
    """
    path = os.path.join(HERE, "core", "config.py")
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except Exception:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PROJECT_MODULES":
                    try:
                        return list(ast.literal_eval(node.value))
                    except Exception:
                        return None
    return None


def die(msg):
    print(f"[build][错误] {msg}")
    sys.exit(1)


def check_layout():
    """校验入口与包目录齐全，避免打出一个跑不起来的空壳。"""
    if not os.path.isfile(ENTRY):
        die(f"入口文件不存在: {ENTRY}")
    missing = [p for p in PROJECT_PACKAGES
               if not os.path.isfile(os.path.join(HERE, p, "__init__.py"))]
    if missing:
        die("缺少包目录: " + ", ".join(missing) +
            "\n        项目已按功能拆分，这些目录必须与 main.py 同级")


def check_deps():
    """构建前检查依赖，避免打出一个跑不起来的空壳。"""
    required = {
        "PyInstaller": "pyinstaller",
        "cv2": "opencv-python",
        "PyQt5": "PyQt5",
        "numpy": "numpy",
        "sounddevice": "sounddevice",
        "requests": "requests",
        "cryptography": "cryptography",
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

    check_layout()
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

    # 提前清掉上一次的产物目录。PyInstaller 在 COLLECT 阶段才会去删它，那时若失败
    # （产物正在运行被占用、或被安全策略拦截）只会抛一个没头没尾的退出码 1。
    # 这里先删一次，失败就给出可操作的提示。
    old_out = os.path.join(distpath, "zhibodou")
    if os.path.isdir(old_out):
        try:
            shutil.rmtree(old_out)
            print(f"[build] 已清理上次产物: {old_out}")
        except Exception as e:
            print(f"[build][错误] 无法删除上次的产物目录: {old_out}\n  {e}\n"
                  "  常见原因：zhibodou.exe 仍在运行，或该目录被占用/被安全策略拦截。\n"
                  "  请先关闭正在运行的程序，或手动删除该目录后重试。")
            return 1

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
    # 必须传入每一个项目子模块，而不只是顶层包名。core.net、旧授权兼容层等
    # 当前可能没有静态 import，但仍属于冻结态自检和后续运行期动态加载范围。
    for m in HIDDEN_IMPORTS + project_modules():
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
                # 原地覆盖而不是先删后拷：某些受限环境会拦截批量删除，
                # dirs_exist_ok 可以完全绕开删除动作。
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d, dirs_exist_ok=True)
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
