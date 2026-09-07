# -*- coding: utf-8 -*-
"""主播会话：把「采集 -> 处理 -> 推流」串起来。

职责边界：
  * 只做编排，不关心具体怎么编码（那是 streaming/ 的事）；
  * 只做编排，不关心界面怎么刷新（UI 通过 get_latest_frame 拉帧）。
采集线程把原始帧放进队列，produce_push_frame 做美颜/裁竖屏/缩放后交给推流器。
"""
import os
import queue
import threading
import time
from collections import deque

import cv2
import numpy as np
from PyQt5.QtCore import QMutex, QMutexLocker

from capture.audio import AudioHost
from capture.resolution import get_cached_resolutions
from core.config import (BASE_FPS, VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT,
                         RTMP_PUSH_URL, AUDIO_RATE, AUDIO_CHANNELS,
                         MAX_VIDEO_BUFFER, SOURCE_TYPE_CAM, SOURCE_TYPE_LIVE)
from pdk import live_service
from processing.image import crop_to_portrait, beauty_process
from processing.live import LiveStreamParser
from streaming.factory import create_pusher




class HostStream:
    def __init__(self):
        self.running = False
        self.mutex = QMutex()
        self.cap = None
        self.cap_running = False
        self._cap_thread = None
        self.cap_frame_queue = deque(maxlen=MAX_VIDEO_BUFFER)
        self.frame_seq = 0            # 采集帧序号，用于避免重复处理同一帧
        self._pushed_seq = -1
        self._pushed_frame = None
        self.audio_host = AudioHost()
        self.camera_ready = False
        self.bright = 50
        self.contrast = 50
        self.sat = 50
        self.sharp = 50
        self.source_type = SOURCE_TYPE_CAM
        self.live_stream_url = ""
        self.live_cap = None
        # 摄像头采集分辨率（默认横屏 720p；UI 可改为竖屏 720p 等）
        self.capture_w = 1280
        self.capture_h = 720

        # RTMP 推流相关
        self.push_video_queue = queue.Queue(maxsize=10)
        self.push_audio_queue = queue.Queue(maxsize=300)
        self.pusher = None
        self.push_backend = None      # "pyav" / "ffmpeg" / None
        self.push_error = None
        self.push_state = "idle"      # idle / running / reconnecting / fatal
        # 后端签发的推流票据（仅在内存中短暂保存，不落盘、不打印完整 URL）
        self.publish_url = None
        self.live_session_no = None

    def set_live_source(self, live_url):
        self.source_type = SOURCE_TYPE_LIVE
        stream_url = LiveStreamParser.parse_douyin_url(live_url)
        if not stream_url:
            print("[主播] 直播链接解析失败")
            return False
        self.live_stream_url = stream_url
        if self.live_cap:
            self.live_cap.release()
        self.live_cap = cv2.VideoCapture(self.live_stream_url)
        self.live_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # 切到线上源时释放物理摄像头，避免同时占用两个设备
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.camera_ready = True
        print(f"[主播] 切换线上直播源：{self.live_stream_url}")
        return True

    def set_cam_source(self):
        self.source_type = SOURCE_TYPE_CAM
        if self.live_cap:
            self.live_cap.release()
            self.live_cap = None
        if self.cap is None or not self.cap.isOpened():
            self.cap = self._get_physical_camera()
            if self.cap is not None and self.cap.isOpened():
                self.camera_ready = True
        print("[主播] 切回摄像头采集")

    def set_capture_resolution(self, w, h):
        """设置摄像头采集分辨率；若摄像头已打开则立即生效。"""
        self.capture_w = w
        self.capture_h = h
        if self.cap is not None and self.cap.isOpened():
            try:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                print(f"[主播] 摄像头分辨率已切换为 {w}x{h}")
            except Exception as e:
                print(f"[主播] 设置分辨率失败: {e}")

    def _get_physical_camera(self):
        """打开摄像头并尝试应用所选采集分辨率。

        关键点：部分摄像头驱动在 set 到不支持的竖屏尺寸（如 720x1280）后，
        后续 read() 会直接进入底层错误状态并使整个进程崩溃（无 Python 异常、
        程序瞬间消失）。因此这里用 cap.get 验证分辨率是否真正生效；若不支持
        则放弃该尺寸、回退到摄像头原生分辨率（由 crop_to_portrait 负责裁竖屏）。
        """
        want = (self.capture_w, self.capture_h)
        # 若目标尺寸不在实测支持列表里，就完全不去 set —— 直接用原生分辨率。
        # 对未经实测的尺寸调 set 正是此前进程瞬间消失的根源之一。
        supported = get_cached_resolutions()
        apply_size = want in supported
        if not apply_size:
            print(f"[主播] {want[0]}x{want[1]} 不在实测支持列表，改用摄像头原生分辨率")

        # 只用 DSHOW（Windows 最稳）；CAP_MSMF 打开不存在的设备索引会直接崩进程，不碰。
        backend_list = [cv2.CAP_DSHOW, cv2.CAP_ANY] if os.name == "nt" else [cv2.CAP_ANY]
        for backend in backend_list:
            for i in (0, 1):
                cap = None
                try:
                    cap = cv2.VideoCapture(i, backend)
                    if not cap.isOpened():
                        if cap is not None:
                            cap.release()
                        continue
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if apply_size:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.capture_w)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.capture_h)
                        # 双保险：即便在支持列表里，也要回读确认真正生效
                        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                        ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                        if aw != self.capture_w or ah != self.capture_h:
                            print(f"[主播] 设备 #{i} 未接受 {want[0]}x{want[1]}，回退原生分辨率")
                            cap.release()
                            cap = cv2.VideoCapture(i, backend)
                            if not cap.isOpened():
                                cap.release()
                                continue
                            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.shape[0] > 0:
                        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                        ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                        print(f"[主播] 摄像头已打开 #{i} @ {aw}x{ah}")
                        return cap
                    cap.release()
                except Exception as e:
                    print(f"[主播] 打开摄像头 #{i} 异常: {e}")
                    try:
                        if cap is not None:
                            cap.release()
                    except Exception:
                        pass
                    continue
        print("[主播] 未找到可用摄像头")
        return None

    def _cap_reader(self):
        frame_interval = 1.0 / BASE_FPS
        last_time = time.time()
        while self.cap_running:
            frame = None
            ret = False
            try:
                if self.source_type == SOURCE_TYPE_CAM and self.cap is not None:
                    ret, frame = self.cap.read()
                elif self.source_type == SOURCE_TYPE_LIVE and self.live_cap is not None:
                    ret, frame = self.live_cap.read()
            except Exception as e:
                print(f"[采集] cap.read 异常: {e}")
                time.sleep(0.1)
                last_time = time.time()
                continue
            if ret and frame is not None:
                with QMutexLocker(self.mutex):
                    self.cap_frame_queue.append(frame)
                    self.frame_seq += 1
            now = time.time()
            sleep = frame_interval - (now - last_time)
            if sleep > 0:
                time.sleep(sleep)
            last_time = now

    # ---------------- RTMP 推流 ----------------
    def produce_push_frame(self):
        """产出一帧用于推流的画面：美颜 -> 中心裁切竖屏 -> 缩放到 720x1280。

        同一帧只处理一次：摄像头未出新帧时直接复用上次结果，避免重复的
        美颜/缩放运算白白吃掉 CPU（CPU 被占满会引发音频 input overflow）。
        """
        with QMutexLocker(self.mutex):
            if not self.cap_frame_queue:
                return None
            seq = self.frame_seq
            if seq == self._pushed_seq and self._pushed_frame is not None:
                return self._pushed_frame
            raw = self.cap_frame_queue[-1]
        proc = beauty_process(raw, self.bright, self.contrast, self.sat, self.sharp)
        proc = crop_to_portrait(proc)
        proc = cv2.resize(proc, (VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT),
                          interpolation=cv2.INTER_LINEAR)
        self._pushed_seq = seq
        self._pushed_frame = proc
        return proc

    def _pop_audio_chunk(self):
        try:
            return self.push_audio_queue.get_nowait()
        except queue.Empty:
            return None

    def _on_push_state(self, state, detail):
        """推流器状态回调（重连中 / 已恢复 / 彻底失败）。"""
        self.push_state = state
        if state == "fatal":
            self.push_error = detail or "RTMP 连接中断"
            self.running = False
        elif state == "reconnected":
            self.push_error = None
            self.push_state = "running"
        elif state == "reconnecting":
            self.push_error = detail

    def _create_pusher(self, push_url):
        """按运行环境选择推流后端：优先 PyAV（纯 Python），否则 ffmpeg。

        后端选择、dshow 音频设备名匹配等细节都下沉到 streaming.factory，
        本类只负责提供当前选中的麦克风名与美颜参数。
        """
        return create_pusher(mic_name=self.audio_host.get_device_name(),
                             beauty=(self.bright, self.contrast, self.sat),
                             on_state=self._on_push_state,
                             push_url=push_url)

    def init_camera_only(self):
        """打开摄像头用于预览（不强制授权，推流时才校验授权）。
        已打开且已就绪时直接返回，幂等可重复调用。"""
        if self.source_type == SOURCE_TYPE_CAM:
            if self.cap is not None and self.cap.isOpened() and self.cap_frame_queue:
                self.camera_ready = True
                return True
        self.cap_running = True
        if self.source_type == SOURCE_TYPE_CAM:
            self.cap = self._get_physical_camera()
            if self.cap is None or not self.cap.isOpened():
                self.cap_running = False
                print("[主播] 摄像头打开失败")
                return False
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            self.camera_ready = True
            return True
        if not getattr(self, "_cap_thread", None) or not self._cap_thread.is_alive():
            self._cap_thread = threading.Thread(target=self._cap_reader, daemon=True)
            self._cap_thread.start()
        for _ in range(30):
            if self.cap_frame_queue:
                self.camera_ready = True
                print("[主播] 摄像头就绪")
                return True
            time.sleep(0.1)
        self.cap_running = False
        print("[主播] 摄像头初始化超时")
        return False

    def start_streaming(self, title: str = ""):
        if not self.camera_ready:
            print("[主播] 摄像头未就绪")
            return False
        # 0) 清理上一轮遗留的推流器（例如上次断流后未及时回收）
        if self.pusher is not None:
            self.stop_streaming()
        # 1) 推流地址：正式 PDK 会话向后端申请短效票据（publishUrl 不透明、
        #    不复用、不落盘）；未登录 PDK（本地 MediaMTX/开发场景）回落本地地址。
        push_url = RTMP_PUSH_URL
        self.publish_url = None
        self.live_session_no = None
        if live_service.is_backend_managed():
            try:
                ticket = live_service.acquire_push_ticket(title=title)
            except live_service.LivePushError as exc:
                self.push_error = str(exc)
                print(f"[主播] 申请推流地址失败: {exc}")
                return False
            push_url = ticket["publish_url"]
            self.publish_url = push_url
            self.live_session_no = ticket["session_no"]
            print(f"[主播] 已获取推流票据: session={ticket['session_no'][:16]}… "
                  f"ttl={ticket['ttl_seconds']}s host={live_service.redact_host(push_url)}")
        # 2) 选择推流后端
        self.pusher, self.push_backend = self._create_pusher(push_url)
        if self.pusher is None:
            self.push_error = "未找到可用的推流后端（需要安装 PyAV 或系统 ffmpeg）"
            print("[主播] " + self.push_error)
            self._discard_ticket()
            return False
        if live_service.is_backend_managed() and hasattr(self.pusher, "max_reconnect"):
            # 后端 publishUrl 是一次性短效票据，连接断开后不能复用旧 URL 重连。
            self.pusher.max_reconnect = 0
        # 3) 仅 PyAV 后端需要 Python 采集音频；ffmpeg 后端由 ffmpeg 直接采集
        if self.push_backend == "pyav":
            self.audio_host.set_push_queue(self.push_audio_queue)
            if not self.audio_host.start_mic_only():
                print("[主播] 警告：麦克风启动失败，将只推视频")
            else:
                print("[主播] 麦克风启动成功")
        else:
            print("[主播] ffmpeg 后端将自行采集音频，跳过 Python 麦克风采集")
        # 4) 启动推流
        audio_getter = self._pop_audio_chunk if self.push_backend == "pyav" else None
        ok = self.pusher.start(video_getter=self.produce_push_frame, audio_getter=audio_getter)
        if not ok:
            self.push_error = getattr(self.pusher, "error", "推流启动失败")
            print(f"[主播] 推流启动失败: {self.push_error}")
            self.pusher = None
            self.audio_host.stop()
            self._discard_ticket()   # 票据未真正使用，释放服务端会话
            return False
        self.running = True
        self.push_state = "running"
        self.push_error = None
        # 安全要求：日志只记 host 与会话号，不输出完整 publishUrl。
        print(f"[主播] RTMP 推流已启动（后端: {self.push_backend}）"
              f" host={live_service.redact_host(push_url)}")
        return True

    def _discard_ticket(self):
        """丢弃当前票据并尽力释放服务端会话（启动失败/中断时调用）。"""
        session_no = self.live_session_no
        self.publish_url = None
        self.live_session_no = None
        if session_no:
            live_service.release_stream(session_no)

    def start(self):
        return self.init_camera_only() and self.start_streaming()

    def get_latest_frame(self):
        with QMutexLocker(self.mutex):
            return self.cap_frame_queue[-1].copy() if self.cap_frame_queue else None

    def get_status(self):
        return {
            "running": self.running,
            "camera_ready": self.camera_ready,
            "source_type": self.source_type,
            "push_backend": self.push_backend,
            "push_error": self.push_error,
            "push_state": self.push_state,
            "video_buffer": len(self.cap_frame_queue),
            "audio_queue": self.push_audio_queue.qsize() if self.push_audio_queue else 0,
        }

    def stop_streaming(self):
        """仅停止 RTMP 推流（麦克风+编码器），保留摄像头与采集线程，预览画面继续显示。"""
        self.running = False
        if self.pusher:
            try:
                self.pusher.stop()
            except Exception as e:
                print(f"[主播] 停止推流异常: {e}")
            self.pusher = None
        self.audio_host.stop()
        # 通知服务端结束直播会话（异步、尽力而为），刷新剩余次数由巡检完成。
        self._discard_ticket()
        self.push_error = None
        self.push_state = "idle"
        print("[主播] 推流已停止（保留摄像头预览）")

    def stop(self):
        self.running = False
        self.cap_running = False
        if self.pusher:
            try:
                self.pusher.stop()
            except Exception as e:
                print(f"[主播] 停止推流异常: {e}")
            self.pusher = None
        self.audio_host.stop()
        self._discard_ticket()
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.live_cap:
            self.live_cap.release()
            self.live_cap = None
        with QMutexLocker(self.mutex):
            self.cap_frame_queue.clear()
        print("[主播] 已停止")
