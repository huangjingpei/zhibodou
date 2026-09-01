# -*- coding: utf-8 -*-
"""摄像头分辨率探测。

为什么必须放进子进程：部分摄像头驱动在 set 到不支持的尺寸后，read() 会
直接触发 C 层崩溃 —— Python 的 try/except 与 Qt 的异常兜底都拦不住，进程
瞬间消失。因此无论开发还是打包环境，探测一律放到独立子进程，崩了也只是
子进程，主程序继续走兜底列表。

收敛策略（每一条都是为了避开已知的驱动级崩溃点）：
  * 只用 CAP_DSHOW，Windows 上最稳；CAP_MSMF 打开不存在的设备索引会崩进程。
  * 设备索引只试 0 和 1。
  * set 之后必须 get 回读且精确相等，才允许 read。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

from core.config import PROBE_ARG
from core.runtime import app_dir, entry_script, IS_FROZEN, CREATE_NO_WINDOW

# 探测结果缓存：避免每次重建 UI / 启动时都重新打开摄像头
_RES_CACHE = None


def get_cached_resolutions():
    """返回分辨率下拉框用的列表：内存缓存 -> 磁盘缓存 -> 静态安全列表（不触碰摄像头）。

    注意：静态兜底仅包含横屏安全分辨率；竖屏(如 720x1280)只有在摄像头被实测
    真正支持时才会出现，避免出现「选了但实际不支持」导致崩溃或无意义选项。
    """
    global _RES_CACHE
    if _RES_CACHE is not None:
        return _RES_CACHE
    disk = load_res_cache_from_disk()
    if disk:
        _RES_CACHE = disk
        return disk
    return list(SAFE_FALLBACK_RES)

class ResProbeThread(QThread):
    """后台探测摄像头真实支持的分辨率，避免在主线程/启动时同步打开摄像头。"""
    done = pyqtSignal(list)
    def run(self):
        global _RES_CACHE
        res = enumerate_camera_resolutions(cancelled=self.isInterruptionRequested)
        if self.isInterruptionRequested():
            return
        _RES_CACHE = res
        self.done.emit(res)

# 探测候选分辨率：横屏在前，竖屏在后（竖屏需实测支持才会进入列表）
PROBE_CANDIDATES = [
    (1920, 1080), (1600, 900), (1366, 768), (1280, 720), (1024, 576),
    (960, 540), (854, 480), (800, 600), (640, 480), (640, 360), (320, 240),
    (1080, 1920), (900, 1600), (720, 1280), (576, 1024), (540, 960),
    (480, 854), (480, 640), (360, 640), (240, 320),
]

# 静态安全兜底：仅横屏常见尺寸，任何摄像头基本都能接受
SAFE_FALLBACK_RES = [(1280, 720), (960, 540), (854, 480), (640, 480),
                     (640, 360), (320, 240)]

# 子进程探测的命令行开关：exe 以该参数自调用时只做探测、不启动界面
PROBE_ARG = "--probe-cam"


def _res_cache_path():
    return os.path.join(app_dir(), "camres.json")


def _res_flag_path():
    """探测进行中标记：若启动时该文件仍存在，说明上次探测把进程搞崩了。"""
    return os.path.join(app_dir(), "camres.probing")


def load_res_cache_from_disk():
    """读取磁盘上的探测结果，避免每次启动都去碰摄像头。失败返回 None。"""
    try:
        with open(_res_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        res = [(int(w), int(h)) for w, h in data.get("resolutions", [])]
        return res or None
    except Exception:
        return None


def save_res_cache_to_disk(res):
    try:
        with open(_res_cache_path(), "w", encoding="utf-8") as f:
            json.dump({"resolutions": [[w, h] for (w, h) in res]}, f)
    except Exception:
        pass


def probe_resolutions_core(on_found=None):
    """实际探测逻辑（主进程与 worker 子进程共用）。

    收敛策略（每一条都是为了避开已知的驱动级崩溃点）：
      * 只用 CAP_DSHOW —— Windows 上最稳；CAP_MSMF 打开不存在的设备索引
        是经典的进程级崩溃点，这里完全不碰。
      * 设备索引只试 0 和 1，不再盲扫到 4。
      * set 之后必须 get 回读且精确相等，才允许 read；否则跳过，
        绝不在驱动的坏状态下读帧。
    """
    found, seen = [], set()
    backends = [cv2.CAP_DSHOW] if os.name == "nt" else [cv2.CAP_ANY]
    for backend in backends:
        for idx in (0, 1):
            cap = None
            try:
                cap = cv2.VideoCapture(idx, backend)
                if not cap.isOpened():
                    continue
                for (w, h) in PROBE_CANDIDATES:
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                        ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                        if aw != w or ah != h:
                            continue
                        ret, frame = cap.read()
                        if not (ret and frame is not None):
                            continue
                        if frame.shape[1] != w or frame.shape[0] != h:
                            continue
                        if (w, h) not in seen:
                            seen.add((w, h))
                            found.append((w, h))
                            if on_found:
                                on_found(w, h)
                    except Exception:
                        continue
                if found:
                    return found  # 第一个可用摄像头探测完即可
            except Exception:
                continue
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
    return found


def run_probe_worker(outfile):
    """worker 子进程入口：只探测、写结果文件、立刻退出，绝不创建界面。

    即便探测过程触发驱动级崩溃，死的也只是这个子进程，主程序毫发无伤。
    """
    res = []
    try:
        res = probe_resolutions_core()
    except Exception:
        res = []
    try:
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump([[w, h] for (w, h) in res], f)
    except Exception:
        pass
    # 用 _exit 跳过 atexit / 析构，避免 OpenCV 释放阶段再次崩溃影响退出码
    os._exit(0)


def _probe_camera_resolutions_subprocess(cancelled=None):
    """在独立子进程中探测摄像头分辨率；打包后通过 exe 自调用实现。

    部分摄像头驱动在 set 到不支持的尺寸后 read() 会直接让进程崩溃——这属于
    C 层崩溃，Python 的 try/except 与 Qt 的异常兜底都拦不住。因此无论开发还是
    打包环境，探测一律放到独立子进程；崩了也只是子进程，主程序继续走兜底列表。
    """
    tmpfile = os.path.join(tempfile.gettempdir(),
                           "zhibodou_camres_%d.json" % os.getpid())
    try:
        if IS_FROZEN:
            cmd = [sys.executable, PROBE_ARG, tmpfile]
        else:
            cmd = [sys.executable, entry_script(), PROBE_ARG, tmpfile]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30.0
        while proc.poll() is None and time.monotonic() < deadline:
            if cancelled is not None and cancelled():
                break
            time.sleep(0.05)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            return []
        try:
            with open(tmpfile, "r", encoding="utf-8") as f:
                return [(int(w), int(h)) for w, h in json.load(f)]
        except Exception:
            return []   # 文件不存在 = 子进程崩溃，交由上层用兜底列表
    except Exception:
        return []
    finally:
        try:
            if os.path.exists(tmpfile):
                os.remove(tmpfile)
        except Exception:
            pass


def enumerate_camera_resolutions(cancelled=None):
    """获取摄像头支持的分辨率列表 [(w, h), ...]（横屏在前、同组内按面积降序）。

    优先级：磁盘缓存 -> 子进程探测 -> 安全静态兜底。
    竖屏分辨率（如 720x1280）只有实测支持时才会出现在结果中。
    """
    cached = load_res_cache_from_disk()
    if cached:
        return cached

    flag = _res_flag_path()
    # 上次探测留下的标记还在 => 上次探测让进程崩了，这次不再冒险
    if os.path.exists(flag):
        print("[分辨率] 检测到上次探测异常退出，本次改用安全列表（删除 camres.json 可重新探测）")
        try:
            os.remove(flag)
        except Exception:
            pass
        save_res_cache_to_disk(SAFE_FALLBACK_RES)
        return list(SAFE_FALLBACK_RES)

    try:
        with open(flag, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    res = _probe_camera_resolutions_subprocess(cancelled=cancelled)

    if cancelled is not None and cancelled():
        return list(SAFE_FALLBACK_RES)

    try:
        if os.path.exists(flag):
            os.remove(flag)
    except Exception:
        pass

    if not res:
        print("[分辨率] 探测未返回结果，使用安全兜底列表")
        res = list(SAFE_FALLBACK_RES)
    res.sort(key=lambda it: (0 if it[0] >= it[1] else 1, -(it[0] * it[1])))
    save_res_cache_to_disk(res)
    return res
