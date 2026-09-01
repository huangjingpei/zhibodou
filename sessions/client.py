# -*- coding: utf-8 -*-
"""观众会话：从中继服务器（或本地直播源）拉流，输出到虚拟摄像头与扬声器。

视频走 TCP 收帧（4 字节长度头 + JPEG/编码帧），音频走独立 TCP 通道。
"""
import socket
import struct
import threading
import time
from collections import deque

import cv2
import numpy as np
import pyvirtualcam
import sounddevice as sd
from PyQt5.QtCore import QObject, QMutex, QMutexLocker, pyqtSignal

from core.config import (AUDIO_RATE, AUDIO_CHANNELS, AUDIO_BLOCK, AUDIO_LATENCY,
                         AUDIO_OVERFLOW_CLEAR, BASE_FPS,
                         RELAY_SERVER_IP, RELAY_CLIENT_VIDEO_PORT,
                         RELAY_CLIENT_AUDIO_PORT,
                         PREVIEW_WIDTH, PREVIEW_HEIGHT,
                         VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT)
from processing.image import crop_to_portrait, beauty_process
from processing.live import LiveStreamParser


# ============================================================
# 客户端类（子机端）- 修复版
# ============================================================
class AudioClient(QObject):
    vol_sig = pyqtSignal(int)
    def __init__(self):
        super().__init__()
        self.sock = None
        self.running = False
        self.stream = None
        self.device_id = None
        self.audio_buf = b""
        self.volume = 0.82
        self.last_vol = 15
        self.audio_packet_count = 0

    def set_volume(self, val):
        self.volume = max(0.0, min(1.2, val / 100.0))

    def set_speaker_device(self, dev_id):
        self.device_id = dev_id
        print(f"[子机音频] 选择扬声器设备ID: {dev_id}")

    def _play_audio(self, outdata, frames, time, status):
        outdata[:] = 0
        need = frames * 2
        if len(self.audio_buf) < need:
            return
        chunk = self.audio_buf[:need]
        self.audio_buf = self.audio_buf[need:]
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        samples *= self.volume
        outdata[:, 0] = samples
        self.audio_packet_count += 1
        if self.audio_packet_count % 50 == 0:
            print(f"[子机音频] 🔊 已播放 {self.audio_packet_count} 包")
        self.vol_sig.emit(max(15, min(100, int(np.max(np.abs(samples)) * 220))))

    def start(self):
        self.running = True
        self.audio_buf = b""
        self.audio_packet_count = 0
        if self.device_id is None:
            try:
                self.device_id = sd.default.device[1]
                print(f"[子机音频] 使用默认扬声器: {self.device_id}")
            except:
                self.device_id = 0
        try:
            self.stream = sd.OutputStream(
                samplerate=AUDIO_RATE, 
                blocksize=AUDIO_BLOCK,
                device=self.device_id, 
                channels=AUDIO_CHANNELS,
                callback=self._play_audio, 
                latency=AUDIO_LATENCY
            )
            self.stream.start()
            print(f"[子机音频] ✅ 扬声器已启动 (设备ID: {self.device_id})")
        except Exception as e:
            print(f"[子机音频] ❌ 扬声器启动失败: {e}")
        threading.Thread(target=self._recv, daemon=True).start()

    def _recv(self):
        """子机音频接收 - 修复版"""
        while self.running:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock.settimeout(5.0)
                self.sock.connect((RELAY_SERVER_IP, RELAY_CLIENT_AUDIO_PORT))
                print(f"[子机音频] ✅ 已连接 {RELAY_SERVER_IP}:{RELAY_CLIENT_AUDIO_PORT}")
                
                self.sock.settimeout(2.0)
                while self.running:
                    try:
                        head = b""
                        while len(head) < 4 and self.running:
                            tmp = self.sock.recv(4 - len(head))
                            if not tmp:
                                raise ConnectionError("连接断开")
                            head += tmp
                        alen = struct.unpack("!I", head)[0]
                        
                        # 每30包打印一次日志
                        if self.audio_packet_count % 30 == 0:
                            print(f"[子机音频] 收到音频包，大小: {alen} 字节")
                        
                        data = b""
                        while len(data) < alen and self.running:
                            tmp = self.sock.recv(alen - len(data))
                            if not tmp:
                                raise ConnectionError("帧接收中断")
                            data += tmp
                        self.audio_buf += data
                        mx = AUDIO_OVERFLOW_CLEAR * AUDIO_BLOCK * 2
                        if len(self.audio_buf) > mx:
                            self.audio_buf = self.audio_buf[-mx:]
                    except socket.timeout:
                        continue
                    except ConnectionError as e:
                        print(f"[子机音频] ❌ 连接错误: {e}")
                        break
            except ConnectionRefusedError:
                print(f"[子机音频] ❌ 连接被拒绝，请检查服务器端口 {RELAY_CLIENT_AUDIO_PORT} 是否开放")
                time.sleep(5)
            except Exception as e:
                print(f"[子机音频] ❌ 连接失败: {e}")
                time.sleep(3)
            finally:
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                    self.sock = None

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

class ClientStream(QObject):
    frame_cb = pyqtSignal(object)
    auto_connected_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.frame_queue = deque(maxlen=8)
        self.mutex = QMutex()
        self.audio_client = AudioClient()
        self.vcam = None
        self.bright = 50
        self.contrast = 50
        self.sat = 50
        self.sharp = 50
        self.local_live_cap = None
        self.use_local_live = False
        self.frame_count = 0

    def start_local_live_stream(self, url):
        self.stop()
        self.use_local_live = True
        stream_url = LiveStreamParser.parse_douyin_url(url)
        if not stream_url:
            return False
        self.local_live_cap = cv2.VideoCapture(stream_url)
        if not self.local_live_cap.isOpened():
            return False
        self.running = True
        self._start_vcam()
        threading.Thread(target=self._local_live_recv, daemon=True).start()
        self.audio_client.start()
        print("[子机] 本地独立拉流已启动（不经过云服务器）")
        return True

    def _local_live_recv(self):
        lt = time.time()
        while self.running and self.use_local_live and self.local_live_cap and self.local_live_cap.isOpened():
            ret, frame = self.local_live_cap.read()
            if ret and frame is not None:
                with QMutexLocker(self.mutex):
                    self.frame_queue.append(frame)
            now = time.time()
            if now - lt < 1/BASE_FPS:
                time.sleep(1/BASE_FPS - (now - lt))
            lt = now

    def start(self):
        self.stop()
        self.running = True
        self.frame_count = 0
        self.audio_client.start()
        self._start_vcam()
        threading.Thread(target=self._recv_loop, daemon=True).start()
        self.auto_connected_sig.emit(RELAY_SERVER_IP)

    def _start_vcam(self):
        threading.Thread(target=self._preview_loop, daemon=True).start()
        try:
            self.vcam = pyvirtualcam.Camera(width=1280, height=720, fps=BASE_FPS)
            threading.Thread(target=self._vcam_loop, daemon=True).start()
            print("[子机] 虚拟摄像头已启动")
        except Exception as e:
            print("虚拟摄像头启动失败，请检查驱动:", e)
            self.vcam = None

    def _preview_loop(self):
        lt = time.time()
        while self.running:
            frame = None
            with QMutexLocker(self.mutex):
                if self.frame_queue:
                    frame = self.frame_queue.pop()
            if frame is not None:
                proc = beauty_process(frame, self.bright, self.contrast, self.sat, self.sharp)
                proc = crop_to_portrait(proc)
                self.frame_cb.emit(cv2.resize(proc, (PREVIEW_WIDTH, PREVIEW_HEIGHT)))
            now = time.time()
            if now - lt < 1/15:
                time.sleep(1/15 - (now - lt))
            lt = now

    def _vcam_loop(self):
        lt = time.time()
        while self.running and self.vcam:
            frame = None
            with QMutexLocker(self.mutex):
                if self.frame_queue:
                    frame = self.frame_queue.pop()
            if frame is not None:
                proc = beauty_process(frame, self.bright, self.contrast, self.sat, self.sharp)
                proc = crop_to_portrait(proc)
                proc = cv2.resize(proc, (VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT))
                try:
                    self.vcam.send(cv2.cvtColor(proc, cv2.COLOR_BGR2RGB))
                except:
                    break
            now = time.time()
            if now - lt < 1/BASE_FPS:
                time.sleep(1/BASE_FPS - (now - lt))
            lt = now

    def _recv_loop(self):
        """子机视频接收 - 修复版"""
        while self.running and not self.use_local_live:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(5.0)
                sock.connect((RELAY_SERVER_IP, RELAY_CLIENT_VIDEO_PORT))
                print(f"[子机视频] ✅ 已连接 {RELAY_SERVER_IP}:{RELAY_CLIENT_VIDEO_PORT}")
                
                sock.settimeout(2.0)
                while self.running and not self.use_local_live:
                    try:
                        head = b""
                        while len(head) < 4 and self.running:
                            tmp = sock.recv(4 - len(head))
                            if not tmp:
                                raise ConnectionError("连接断开")
                            head += tmp
                        size = struct.unpack("!I", head)[0]
                        
                        # 每30帧打印一次收到数据
                        if self.frame_count % 30 == 0:
                            print(f"[子机视频] 收到帧，大小: {size} 字节")
                        
                        if size > 2*1024*1024 or size <= 0:
                            continue
                        data = b""
                        while len(data) < size and self.running:
                            tmp = sock.recv(size - len(data))
                            if not tmp:
                                raise ConnectionError("帧接收中断")
                            data += tmp
                        
                        # 检查数据完整性
                        if len(data) != size:
                            print(f"[子机视频] ⚠️ 数据不完整: {len(data)}/{size}")
                            continue
                        
                        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            with QMutexLocker(self.mutex):
                                self.frame_queue.append(frame)
                            self.frame_count += 1
                            if self.frame_count % 30 == 0:
                                print(f"[子机视频] 📺 已接收 {self.frame_count} 帧")
                        else:
                            print(f"[子机视频] ❌ 帧解码失败")
                            
                    except socket.timeout:
                        continue
                    except ConnectionError as e:
                        print(f"[子机视频] ❌ 连接错误: {e}")
                        break
            except ConnectionRefusedError:
                print(f"[子机视频] ❌ 连接被拒绝，请检查服务器端口 {RELAY_CLIENT_VIDEO_PORT} 是否开放")
                time.sleep(5)
            except Exception as e:
                print(f"[子机视频] ❌ 连接失败: {e}")
                time.sleep(3)
            finally:
                try:
                    sock.close()
                except:
                    pass

    def auto_find_and_connect(self):
        self.start()

    def connect_host(self, ip):
        print(f"[子机] 使用硬编码地址 {RELAY_SERVER_IP}")
        self.start()

    def stop(self):
        self.running = False
        self.use_local_live = False
        self.audio_client.stop()
        if self.vcam:
            try:
                self.vcam.close()
            except:
                pass
            self.vcam = None
        if self.local_live_cap:
            self.local_live_cap.release()
            self.local_live_cap = None
        with QMutexLocker(self.mutex):
            self.frame_queue.clear()
        print("[子机] 已停止")
