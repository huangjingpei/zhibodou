import sys
import os
import threading
import socket
import struct
import cv2
import numpy as np
import time
import json
import platform
import uuid
import hashlib
import base64
from collections import deque
from PyQt5.QtCore import Qt, QTimer, QMutex, QMutexLocker, pyqtSignal, QObject, QThread
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QSlider, QCheckBox,
    QComboBox, QMessageBox, QFrame, QDialog,
    QTextEdit, QScrollArea, QLineEdit
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor
import sounddevice as sd
import pyvirtualcam
import requests
import re
import streamlink
import queue
import subprocess
import shutil
import tempfile
from fractions import Fraction

# ============================================================
# 打包运行期兜底（必须在任何 print 之前完成）
# ============================================================
IS_FROZEN = getattr(sys, "frozen", False)

def _app_dir():
    """程序所在目录：打包后为 exe 目录，开发时为脚本目录。"""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

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
        log_path = os.path.join(_app_dir(), "zhibodou.log")
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
except Exception:
    av = None
    HAVE_AV = False

# ============================================================
# ★ 核心配置（天翼云直推模式）★
# ============================================================
ROLE = "host"
HOST_MODE = "rtmp"

# ============================================================
# ★ RTMP 推流配置（主播端）★
# 推流服务器地址在代码内固定：本机 127.0.0.1
# 若需推到公网，请修改 RTMP_SERVER_IP / RTMP_PORT / RTMP_STREAM_KEY
#
# 关于 MediaMTX 的 stream key：
#   MediaMTX 没有 nginx-rtmp 那种「app/stream」两层概念，它把「端口后整段路径」
#   直接当作流名。因此下面两种写法对 MediaMTX 都合法：
#     嵌套式：RTMP_APP="live", RTMP_STREAM_KEY="zhibodou"
#             -> rtmp://127.0.0.1:1935/live/zhibodou   (流名 = live/zhibodou)
#     扁平式：RTMP_APP="",     RTMP_STREAM_KEY="zhibodou"
#             -> rtmp://127.0.0.1:1935/zhibodou        (流名 = zhibodou)
#   如果 mediamtx.yml 里给路径设了 publishUser/publishPass 发布鉴权，
#   请把账号密码填到 RTMP_PUBLISH_USER / RTMP_PUBLISH_PASS。
# ============================================================
RTMP_SERVER_IP = "125.122.155.133"
RTMP_PORT = 1935
RTMP_APP = "live"
RTMP_STREAM_KEY = "zhibodou"
RTMP_PUBLISH_USER = ""   # MediaMTX 发布鉴权账号（未开启则留空）
RTMP_PUBLISH_PASS = ""   # MediaMTX 发布鉴权密码（未开启则留空）


def _build_rtmp_url():
    """拼接 RTMP 推流地址。APP 留空则扁平；带鉴权则注入 user[:pass]@。"""
    app_part = f"{RTMP_APP}/" if RTMP_APP else ""
    if RTMP_PUBLISH_USER:
        auth = RTMP_PUBLISH_USER
        if RTMP_PUBLISH_PASS:
            auth += f":{RTMP_PUBLISH_PASS}"
        auth += "@"
    else:
        auth = ""
    return f"rtmp://{auth}{RTMP_SERVER_IP}:{RTMP_PORT}/{app_part}{RTMP_STREAM_KEY}"


RTMP_PUSH_URL = _build_rtmp_url()

# 编码参数（竖屏 720x1280 输出）
# 注意：推公网时码率必须小于实际上行带宽，否则 TCP 发送缓冲会塞满并报
#       [Errno 138]（ETIMEDOUT，写超时）。上行不足时请下调此值（如 1_000_000）。
RTMP_VIDEO_BITRATE = 2_000_000      # 2 Mbps
RTMP_AUDIO_BITRATE = 128_000        # 128 kbps
RTMP_PRESET = "veryfast"

# 连接与重连参数
RTMP_OPEN_TIMEOUT = 10.0            # 建立连接超时（秒）
RTMP_RW_TIMEOUT = 5.0               # 单次读写超时（秒），避免卡死在 mux 里
RTMP_MAX_RECONNECT = 5              # 连接中断后的最大重连次数

# ============================================================
# ★ 观众端拉流仍走原中继服务器（如需改为 RTMP 拉流可在此调整）★
# ============================================================
# 原天翼云中继服务器IP（观众端使用，与主播端 RTMP 推流相互独立）
RELAY_SERVER_IP = "125.122.155.138"

# 观众端拉流端口（从中继服务器拉流，与主播端 RTMP 推流相互独立）
RELAY_CLIENT_VIDEO_PORT = 5612    # 子机视频拉流端口
RELAY_CLIENT_AUDIO_PORT = 5613    # 子机音频拉流端口

BROADCAST_PORT = 5499
BROADCAST_MSG = b"ZHIBODOU_LAN"

# ============================================================
# 性能优化参数
# ============================================================
BASE_FPS = 20
VIRTUAL_CAM_WIDTH = 720
VIRTUAL_CAM_HEIGHT = 1280
PREVIEW_WIDTH = 360
PREVIEW_HEIGHT = 640

AUDIO_RATE = 44100
AUDIO_CHANNELS = 1
AUDIO_BLOCK = 2048
AUDIO_LATENCY = "low"
NOISE_REDUCE_THRESHOLD = 0.0003
VOICE_BOOST_RATIO = 1.2
AUDIO_OVERFLOW_CLEAR = 400

SOCKET_TIMEOUT = 15.0

SECRET_KEY = "ZhiBoDou2026"
USER_DATA_PATH = os.path.join(os.path.expanduser("~"), ".ZhiBoDouData")
os.makedirs(USER_DATA_PATH, exist_ok=True)
LICENSE_FILE = os.path.join(USER_DATA_PATH, "license.lic")
PHONE_CFG_FILE = os.path.join(USER_DATA_PATH, "phone_cfg.json")
DAY_SEC = 86400
COUNT_DOWN_SEC = 3

MAX_VIDEO_BUFFER = 5
MAX_AUDIO_BUFFER = 100
RECONNECT_DELAY_MIN = 3
RECONNECT_DELAY_MAX = 30

# ============================================================
# 抖音直播解析模块
# ============================================================
class LiveStreamParser:
    @staticmethod
    def parse_douyin_url(url: str) -> str:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Referer": "https://live.douyin.com/",
                "Accept-Language": "zh-CN,zh;q=0.9"
            }
            if "v.douyin.com" in url:
                resp = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
                final_url = resp.url
            else:
                final_url = url
            room_id = re.search(r"live\.douyin\.com/(\d+)", final_url)
            if not room_id:
                room_id = re.search(r"(\d{18,19})", final_url)
            if not room_id:
                print("[解析] 无法提取直播间ID")
                return ""
            rid = room_id.group(1)
            print(f"[解析] 提取到直播间ID: {rid}")
            api_url = f"https://webcast-hl.amemv.com/webcast/room/reflow/info/?room_id={rid}&live_id=1"
            resp = requests.get(api_url, headers=headers, timeout=10)
            data = resp.json()
            stream_url = ""
            stream_url = data.get("data", {}).get("room", {}).get("stream_url", {}).get("rtmp_pull_url", "")
            if not stream_url:
                stream_url = data.get("data", {}).get("room", {}).get("stream_url", {}).get("flv_pull_url", {}).get("FULL_HD1", "")
            if not stream_url:
                stream_url = data.get("data", {}).get("room", {}).get("stream_url", {}).get("hls_pull_url", "")
            if not stream_url:
                print("[解析] 未获取到直播流地址")
                return ""
            print(f"[解析] 成功获取直播流地址: {stream_url[:50]}...")
            return stream_url
        except Exception as e:
            print(f"[解析] 抖音解析失败：{e}")
            return ""

    @staticmethod
    def read_stream_frame(stream_url: str, width, height):
        try:
            streams = streamlink.streams(stream_url)
            if streams:
                stream = streams["best"]
                cap = cv2.VideoCapture(stream.url)
            else:
                cap = cv2.VideoCapture(stream_url)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            for _ in range(30):
                ret, frame = cap.read()
                if ret and frame is not None:
                    return frame
                time.sleep(0.1)
            print("[解析] 无法读取直播流画面")
            return None
        except Exception as e:
            print(f"[解析] 读取直播流失败：{e}")
            return None

SOURCE_TYPE_CAM = "camera"
SOURCE_TYPE_LIVE = "live"

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

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def start_broadcast():
    local_ip = get_local_ip()
    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            try:
                msg = f"{BROADCAST_MSG.decode()}|{local_ip}".encode()
                sock.sendto(msg, ("255.255.255.255", BROADCAST_PORT))
                time.sleep(0.5)
            except:
                time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()

def save_phone_config(phone):
    try:
        with open(PHONE_CFG_FILE, "w", encoding="utf-8") as f:
            json.dump({"phone": phone}, f, ensure_ascii=False)
    except:
        pass

def load_phone_config():
    if not os.path.exists(PHONE_CFG_FILE):
        return ""
    try:
        with open(PHONE_CFG_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("phone", "")
    except:
        return ""

def get_machine_code():
    return hashlib.md5(f"{platform.processor()}{hex(uuid.getnode())}".encode()).hexdigest().upper()

def encrypt_lic(data):
    return base64.b64encode((json.dumps(data, ensure_ascii=False) + SECRET_KEY).encode()).decode()

def decrypt_lic(enc):
    try:
        raw = base64.b64decode(enc).decode()
        if raw.endswith(SECRET_KEY):
            return json.loads(raw[:-len(SECRET_KEY)])
        return {}
    except:
        return {}

def get_auth_info():
    phone = load_phone_config().strip()
    if len(phone) < 11 or not os.path.exists(LICENSE_FILE):
        return False, 0, 0, 0
    with open(LICENSE_FILE, "r") as f:
        lic = decrypt_lic(f.read().strip())
    if not lic or lic.get("machine_code") != get_machine_code() or lic.get("bind_phone") != phone:
        return False, 0, 0, 0
    remain = max(0, int(lic.get("expire_time", 0) - time.time()))
    return remain > 0, remain, lic.get("days", 0), lic.get("max_client", 0)

def verify_and_save_activate_code(code, phone):
    lic = decrypt_lic(code)
    if not lic or lic.get("machine_code") != get_machine_code():
        return False, "激活码无效或与本机不匹配"
    days, mc = lic.get("days", 0), lic.get("max_client", 0)
    if days <= 0 or mc <= 0:
        return False, "无效的授权信息"
    lic["bind_phone"] = phone
    lic["expire_time"] = time.time() + days * DAY_SEC
    try:
        with open(LICENSE_FILE, "w") as f:
            f.write(encrypt_lic(lic))
        return True, "激活成功"
    except:
        return False, "写入授权文件失败"

class CountDownDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.cnt = COUNT_DOWN_SEC
        self.setWindowTitle("激活成功")
        self.setFixedSize(320, 160)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QDialog{background:#121826;border:1px solid #2d88ff;border-radius:10px;}
            QLabel{color:#00ccff;font-size:14px;}
        """)
        self.label = QLabel(f"授权已激活，{self.cnt}秒后自动关闭")
        self.label.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout()
        lay.addWidget(self.label)
        self.setLayout(lay)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_cnt)
        self.timer.start(1000)
    def update_cnt(self):
        self.cnt -= 1
        self.label.setText(f"授权已激活，{self.cnt}秒后自动关闭")
        if self.cnt <= 0:
            self.timer.stop()
            self.accept()

class VolumeBar(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vol = 15
        self.setFixedHeight(20)
        self.setStyleSheet("""
            background:#1a1a2e;
            border-radius:6px;
            border:1px solid #2d88ff;
        """)
    def set_vol(self, val):
        self.vol = max(15, min(100, val))
        self.update()
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = int(self.width() * self.vol / 100)
        color = QColor(0, 204, 255) if self.vol < 70 else QColor(255, 90, 90)
        p.fillRect(2, 2, w-4, self.height()-4, color)

def crop_to_portrait(frame):
    h, w = frame.shape[:2]
    target_ratio = 9 / 16
    current_ratio = w / h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x_start = (w - new_w) // 2
        return frame[:, x_start:x_start+new_w]
    else:
        new_h = int(w / target_ratio)
        y_start = (h - new_h) // 2
        return frame[y_start:y_start+new_h]

def beauty_process(frame, bright=50, contrast=50, sat=50, sharp=50):
    result = frame.astype(np.float32)
    if bright != 50:
        bright_factor = 1.0 + (bright - 50) / 60.0
        result = result * bright_factor
        result = np.clip(result, 0, 255)
    if contrast != 50:
        alpha = 0.88 + (contrast - 50) / 110
        result = result * alpha
        result = np.clip(result, 0, 255)
    if sat != 50:
        hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] += (sat - 50) * 0.22
        hsv[..., 1] = np.clip(hsv[..., 1], 0, 255)
        result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    if sharp > 50:
        k = (sharp - 50) / 26
        kernel = np.array([[0, -k, 0], [-k, 1+4*k, -k], [0, -k, 0]], np.float32)
        result = cv2.filter2D(result, -1, kernel)
        result = np.clip(result, 0, 255)
    return result.astype(np.uint8)


# ============================================================
# RTMP 推流（主播端）
# 设计：优先用纯 Python（PyAV）采集摄像头+麦克风 -> 编码 -> 推流 RTMP；
#       若环境没有 PyAV，则回退到 ffmpeg（由 ffmpeg 直接采集设备并推流）。
# ============================================================
def find_ffmpeg():
    """查找可用的 ffmpeg 可执行文件：
       1) 系统 PATH
       2) 打包后 exe 同目录 / PyInstaller 临时目录(sys._MEIPASS)
       3) 脚本/工作目录下的本地 ffmpeg(.exe)
       4) imageio-ffmpeg 自带二进制
    """
    # 1) 系统 PATH
    try:
        p = shutil.which("ffmpeg")
        if p:
            return p
    except Exception:
        pass
    # 2) 候选目录：打包环境优先用 exe 所在目录与 _MEIPASS，其次脚本目录/工作目录
    candidate_dirs = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate_dirs.append(exe_dir)
        # PyInstaller 6.x 的 one-folder 新布局会把依赖放在 _internal 子目录
        candidate_dirs.append(os.path.join(exe_dir, "_internal"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate_dirs.append(meipass)
    candidate_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    candidate_dirs.append(os.getcwd())
    for d in candidate_dirs:
        for cand in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                return p
    # 3) imageio-ffmpeg 自带
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def list_dshow_devices():
    """列出 Windows DirectShow 的视频/音频设备名称（仅 ffmpeg 回退方案使用）。"""
    exe = find_ffmpeg()
    if not exe:
        return [], []
    try:
        out = subprocess.run([exe, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                             capture_output=True, text=True, timeout=20,
                             creationflags=CREATE_NO_WINDOW).stderr
    except Exception as e:
        print(f"[dshow] 列举设备失败: {e}")
        return [], []
    vids, auds = [], []
    cur = None
    for line in out.splitlines():
        if "DirectShow video devices" in line:
            cur = vids
        elif "DirectShow audio devices" in line:
            cur = auds
        elif cur is not None:
            m = re.search(r'"([^"]+)"', line)
            if m:
                cur.append(m.group(1))
    return vids, auds


class PyAVRtmpPusher:
    """纯 Python 推流：由调用方持续提供视频帧(BGR)与音频块(int16)，本类用 PyAV 编码并推 RTMP。"""

    def __init__(self, url, width, height, fps, audio_rate, audio_channels,
                 video_bitrate=RTMP_VIDEO_BITRATE, audio_bitrate=RTMP_AUDIO_BITRATE,
                 preset=RTMP_PRESET):
        self.url = url
        self.width = width
        self.height = height
        self.fps = fps
        self.audio_rate = audio_rate
        self.audio_channels = audio_channels
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.preset = preset
        self.container = None
        self.vstream = None
        self.astream = None
        self.running = False
        self.thread = None
        self.video_getter = None
        self.audio_getter = None
        self.frame_count = 0
        self.sample_count = 0
        self.error = None
        # 断流/重连状态
        self.fatal = False            # True 表示已彻底放弃（重连次数用尽）
        self.reconnecting = False
        self.reconnect_count = 0
        self.max_reconnect = RTMP_MAX_RECONNECT
        self.on_state = None          # 可选回调：on_state(state:str, detail:str)
        self._last_frame = None       # 摄像头暂时无帧时复用，保持时间轴连续
        self._log_ts = {}             # 日志限频： key -> [上次打印时间, 累计次数]
        self._slow_ticks = 0          # 连续「发送慢于实时」的次数（上行带宽不足信号）

    # ---------- 工具 ----------
    def _log(self, key, msg, interval=5.0):
        """同类日志限频打印，避免刷屏；重复次数在下一次打印时带出。"""
        now = time.time()
        rec = self._log_ts.get(key)
        if rec is None:
            self._log_ts[key] = [now, 0]
            print(msg)
            return
        rec[1] += 1
        if now - rec[0] >= interval:
            extra = f"（{interval:.0f}s 内重复 {rec[1]} 次）" if rec[1] else ""
            print(msg + extra)
            rec[0] = now
            rec[1] = 0

    def _notify(self, state, detail=""):
        if self.on_state:
            try:
                self.on_state(state, detail)
            except Exception:
                pass

    @staticmethod
    def _is_network_error(exc):
        """判断是否为「连接已废」类错误：需要重建连接而不是原地重试。
        Windows 下 ETIMEDOUT=138 / ECONNRESET=10054 / EPIPE=32；FFmpeg 会映射成负 errno。"""
        errno_val = getattr(exc, "errno", None)
        if errno_val is not None and abs(int(errno_val)) in (
                5, 32, 104, 138, 10053, 10054, 10060, 32104):
            return True
        text = str(exc).lower()
        for kw in ("broken pipe", "connection reset", "timed out", "timeout",
                   "end of file", "-138", "i/o error", "errno 138", "errno 32"):
            if kw in text:
                return True
        return isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError, OSError))

    # ---------- 连接管理 ----------
    def _open_container(self):
        """建立 RTMP 连接并创建音视频流。失败抛异常。"""
        options = {
            "flvflags": "no_duration_filesize",
            # 写超时（微秒）：避免 TCP 发送缓冲塞满后一直卡死在 mux 里
            "rw_timeout": str(int(RTMP_RW_TIMEOUT * 1_000_000)),
            "tcp_nodelay": "1",
        }
        try:
            self.container = av.open(self.url, mode="w", format="flv",
                                     options=options,
                                     timeout=(RTMP_OPEN_TIMEOUT, RTMP_RW_TIMEOUT))
        except TypeError:
            # 老版本 PyAV 不支持 timeout 参数
            self.container = av.open(self.url, mode="w", format="flv", options=options)
        # 视频流：限制 VBV，避免瞬时码率峰值把上行打爆
        self.vstream = self.container.add_stream("libx264", rate=self.fps)
        self.vstream.width = self.width
        self.vstream.height = self.height
        self.vstream.pix_fmt = "yuv420p"
        self.vstream.bit_rate = self.video_bitrate
        try:
            self.vstream.codec_context.gop_size = self.fps * 2
        except Exception:
            pass
        self.vstream.codec_context.options = {
            "preset": self.preset,
            "tune": "zerolatency",
            "profile": "main",
            "maxrate": str(self.video_bitrate),
            "bufsize": str(self.video_bitrate * 2),
            "sc_threshold": "0",
        }
        # 音频流（仅在提供了音频源时创建）
        if self.audio_getter is not None:
            self.astream = self.container.add_stream("aac", rate=self.audio_rate)
            self.astream.layout = "mono" if self.audio_channels == 1 else "stereo"
            self.astream.bit_rate = self.audio_bitrate
            self.astream.codec_context.options = {"strict": "experimental"}
        else:
            self.astream = None

    def _close_container(self, flush=False):
        try:
            if flush and self.container is not None:
                if self.vstream is not None:
                    for pkt in self.vstream.encode(None):
                        self.container.mux(pkt)
                if self.astream is not None:
                    for pkt in self.astream.encode(None):
                        self.container.mux(pkt)
        except Exception:
            pass
        try:
            if self.container is not None:
                self.container.close()
        except Exception:
            pass
        self.container = None
        self.vstream = None
        self.astream = None

    def _reconnect(self):
        """连接已废时重建：退避重试，重置时间轴。返回 True 表示重连成功。"""
        self.reconnecting = True
        self._close_container(flush=False)
        while self.running and self.reconnect_count < self.max_reconnect:
            self.reconnect_count += 1
            delay = min(2 ** self.reconnect_count, 10)
            print(f"[PyAV推流] 连接中断，{delay}s 后第 {self.reconnect_count}/{self.max_reconnect} 次重连…")
            self._notify("reconnecting", f"第 {self.reconnect_count} 次重连")
            for _ in range(int(delay * 10)):
                if not self.running:
                    self.reconnecting = False
                    return False
                time.sleep(0.1)
            try:
                self._open_container()
            except Exception as e:
                self.error = str(e)
                print(f"[PyAV推流] 重连失败: {e}")
                self._close_container(flush=False)
                continue
            # 重置时间轴，丢弃旧积压音频
            self.frame_count = 0
            self.sample_count = 0
            self._drain_audio()
            self._log_ts.clear()
            self.reconnecting = False
            self.reconnect_count = 0
            print("[PyAV推流] 重连成功，已恢复推流")
            self._notify("reconnected", "")
            return True
        self.reconnecting = False
        self.fatal = True
        self.running = False
        self.error = self.error or "RTMP 连接中断且重连失败"
        print(f"[PyAV推流] 重连次数用尽，已停止推流：{self.error}")
        self._notify("fatal", self.error)
        return False

    def _drain_audio(self, limit=1000):
        if self.audio_getter is None:
            return
        for _ in range(limit):
            if self.audio_getter() is None:
                break

    # ---------- 启动 / 主循环 ----------
    def start(self, video_getter, audio_getter=None):
        self.video_getter = video_getter
        self.audio_getter = audio_getter
        self.running = True
        self.fatal = False
        self.reconnect_count = 0
        try:
            self._open_container()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            self.error = str(e)
            print(f"[PyAV推流] 启动失败: {e}")
            self._close_container(flush=False)
            self.running = False
            return False

    def _encode_video(self, vbase):
        frame = self.video_getter() if self.video_getter else None
        if frame is None:
            frame = self._last_frame
        else:
            self._last_frame = frame
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        vf.pts = self.frame_count
        vf.time_base = vbase
        self.frame_count += 1
        for pkt in self.vstream.encode(vf):
            self.container.mux(pkt)

    def _encode_audio(self, abase, max_chunks):
        """每轮最多消费 max_chunks 块音频；积压过多时丢弃最旧的，避免音画延迟越拖越大。"""
        if self.audio_getter is None or self.astream is None:
            return
        for _ in range(max_chunks):
            chunk = self.audio_getter()
            if chunk is None:
                return
            # PyAV 要求音频为二维数组 (声道数, 采样数)；麦克风为单声道，故 (1, N)
            arr = np.ascontiguousarray(chunk).reshape(self.audio_channels, -1)
            af = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
            af.sample_rate = self.audio_rate
            af.pts = self.sample_count
            af.time_base = abase
            self.sample_count += arr.shape[1]
            for pkt in self.astream.encode(af):
                self.container.mux(pkt)
        # 仍有积压说明消费不过来，直接丢弃旧数据保实时
        dropped = 0
        while dropped < 200 and self.audio_getter() is not None:
            dropped += 1
        if dropped:
            self._log("audio_drop", f"[PyAV推流] 音频积压，丢弃 {dropped} 块以保持实时")

    def _run(self):
        vbase = Fraction(1, self.fps)
        abase = Fraction(1, self.audio_rate)
        period = 1.0 / self.fps
        # 每帧周期内理论产生的音频块数，留 3 倍余量
        chunks_per_frame = max(1, int(self.audio_rate * period / max(1, AUDIO_BLOCK)) + 1)
        max_chunks = chunks_per_frame * 3
        next_tick = time.perf_counter()
        while self.running:
            try:
                t0 = time.perf_counter()
                self._encode_video(vbase)
                self._encode_audio(abase, max_chunks)
                cost = time.perf_counter() - t0
                # 发送/编码慢于实时，说明上行带宽或 CPU 不足
                if cost > period:
                    self._slow_ticks += 1
                    if self._slow_ticks % 40 == 0:
                        self._log("slow", f"[PyAV推流] 发送慢于实时（单帧耗时 {cost*1000:.0f}ms > "
                                          f"{period*1000:.0f}ms），上行带宽或 CPU 可能不足，"
                                          f"建议下调 RTMP_VIDEO_BITRATE / BASE_FPS")
                else:
                    self._slow_ticks = 0
                # 墙钟节流：严格按 fps 推送，避免以 CPU 全速灌爆上行
                next_tick += period
                sleep = next_tick - time.perf_counter()
                if sleep > 0:
                    time.sleep(sleep)
                elif sleep < -period * 5:
                    next_tick = time.perf_counter()   # 落后太多，重置基准不追帧
            except Exception as e:
                self.error = str(e)
                if self._is_network_error(e):
                    print(f"[PyAV推流] 连接异常: {e}")
                    if not self._reconnect():
                        break
                    next_tick = time.perf_counter()
                else:
                    self._log("loop", f"[PyAV推流] 循环异常: {e}")
                    time.sleep(0.05)
        # 收尾：flush 编码器
        self._close_container(flush=True)

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        self.thread = None


class FFmpegRtmpPusher:
    """回退方案：由 ffmpeg 直接采集摄像头+麦克风（Windows dshow）并推流 RTMP。
    Python 负责选择设备、构造命令、应用美颜/裁切滤镜。"""

    def __init__(self, url, width, height, fps, audio_rate, audio_channels,
                 video_bitrate=RTMP_VIDEO_BITRATE, audio_bitrate=RTMP_AUDIO_BITRATE,
                 preset=RTMP_PRESET):
        self.url = url
        self.width = width
        self.height = height
        self.fps = fps
        self.audio_rate = audio_rate
        self.audio_channels = audio_channels
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.preset = preset
        self.proc = None
        self.running = False
        self.error = None
        self.video_device = None
        self.audio_device = None
        self.beauty = None  # (bright, contrast, sat) 0-100，默认50

    def configure_devices(self, video_device, audio_device, beauty=None):
        self.video_device = video_device
        self.audio_device = audio_device
        self.beauty = beauty

    def _build_video_filter(self):
        # 中心裁切为 9:16 竖屏，再缩放到目标分辨率
        vf = f"crop=ih*9/16:ih,scale={self.width}:{self.height}"
        if self.beauty:
            b, c, s = self.beauty
            bright = (b - 50) / 100.0
            contrast = 1.0 + (c - 50) / 100.0
            sat = 1.0 + (s - 50) / 100.0
            vf = f"eq=brightness={bright:.2f}:contrast={contrast:.2f}:saturation={sat:.2f},{vf}"
        return vf

    def start(self, video_getter=None, audio_getter=None):
        self.running = True
        exe = find_ffmpeg()
        if not exe:
            self.error = "未找到 ffmpeg（请安装 ffmpeg 或 imageio-ffmpeg）"
            return False
        if not self.video_device:
            self.error = "未找到可用的 DirectShow 视频设备"
            return False
        cmd = [
            exe, "-y",
            "-f", "dshow", "-rtbufsize", "100M", "-i", f"video={self.video_device}",
            "-f", "dshow", "-i", f"audio={self.audio_device}",
            "-vf", self._build_video_filter(),
            "-c:v", "libx264", "-preset", self.preset, "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-b:v", str(self.video_bitrate),
            "-g", str(self.fps * 2),
            "-c:a", "aac", "-b:a", str(self.audio_bitrate),
            "-f", "flv", self.url,
        ]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=CREATE_NO_WINDOW)
            print(f"[ffmpeg推流] 已启动 -> {self.url}")
            return True
        except Exception as e:
            self.error = str(e)
            print(f"[ffmpeg推流] 启动失败: {e}")
            return False

    def stop(self):
        self.running = False
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None


def get_all_mic_devices():
    mics = []
    try:
        devs = sd.query_devices()
        for idx, dev in enumerate(devs):
            if dev["max_input_channels"] > 0:
                mics.append((idx, dev["name"]))
    except Exception as e:
        print(f"获取麦克风设备失败: {e}")
    return mics

def get_all_speaker_devices():
    spks = []
    try:
        devs = sd.query_devices()
        for idx, dev in enumerate(devs):
            if dev["max_output_channels"] > 0:
                spks.append((idx, dev["name"]))
    except Exception as e:
        print(f"获取扬声器设备失败: {e}")
    return spks

# ============================================================
# 音频处理类（主播端）
# ============================================================
class AudioHost(QObject):
    vol_sig = pyqtSignal(int)
    def __init__(self):
        super().__init__()
        self.running = False
        self.stream = None
        self.mic_gain = 1.2
        self.device_id = None
        self.last_vol = 15
        # 推流音频队列：由 HostStream 注入；麦克风采集的 PCM 会放入此队列供 RTMP 推流使用
        self.push_queue = None
        self._status_log_ts = 0.0     # 音频状态日志限频
        self._status_count = 0
        self._vol_emit_ts = 0.0       # 音量信号限频（跨线程 emit 太频繁会拖慢主线程）

    def set_mic_gain(self, val):
        self.mic_gain = max(1.0, min(2.2, val / 25))

    def set_mic_device(self, dev_id):
        self.device_id = dev_id
        print(f"[音频] 选择麦克风设备ID: {dev_id}")

    def set_push_queue(self, q):
        """设置推流音频队列（仅 PyAV 推流后端需要）。"""
        self.push_queue = q

    def _audio_callback(self, indata, frames, time_info, status):
        # overflow 只表示上一块被丢过，本块数据依然有效：限频提示但继续处理，
        # 不能直接 return，否则会连带丢掉正常音频并造成推流断续。
        if status:
            self._status_count += 1
            now = time.time()
            if now - self._status_log_ts >= 5.0:
                extra = f"（5s 内共 {self._status_count} 次）" if self._status_count > 1 else ""
                print(f"[音频回调] 状态异常: {status}{extra}，通常是 CPU 繁忙所致，已自动容错")
                self._status_log_ts = now
                self._status_count = 0
        try:
            if indata.shape[1] > 1:
                data = np.mean(indata, axis=1)
            else:
                data = indata.flatten()
            data = data.astype(np.float32, copy=True)

            vol_level = np.max(np.abs(data))
            vol = int(vol_level * 200)
            vol = max(15, min(100, vol))
            self.last_vol = vol
            # 限频 emit：约 10 次/秒足够驱动音量条
            now_v = time.time()
            if now_v - self._vol_emit_ts >= 0.1:
                self._vol_emit_ts = now_v
                self.vol_sig.emit(vol)

            mask = np.abs(data) > NOISE_REDUCE_THRESHOLD
            data[~mask] *= 0.15
            data *= VOICE_BOOST_RATIO

            audio_data = (data * self.mic_gain * 32767).astype(np.int16)
            # 若已配置推流音频队列，则放入队列（非阻塞；满则丢弃最旧的一块，
            # 保留最新音频，避免推流端消费不过来时音画延迟持续累积）
            if self.push_queue is not None:
                try:
                    self.push_queue.put_nowait(audio_data)
                except queue.Full:
                    try:
                        self.push_queue.get_nowait()
                        self.push_queue.put_nowait(audio_data)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[音频回调] 异常: {e}")

    def start_mic_only(self):
        if self.device_id is None:
            try:
                devs = sd.query_devices()
                for idx, dev in enumerate(devs):
                    if dev["max_input_channels"] > 0:
                        self.device_id = idx
                        print(f"[音频] 未手动选择麦克风，自动选用默认设备: {dev['name']} (ID:{idx})")
                        break
                if self.device_id is None:
                    print("[音频] 错误：未检测到可用麦克风设备！")
                    return False
            except Exception as e:
                print(f"[音频] 自动检测麦克风失败: {e}")
                return False

        self.running = True
        try:
            print(f"[音频] 启动麦克风，设备ID: {self.device_id}")
            self.stream = sd.InputStream(
                samplerate=AUDIO_RATE,
                blocksize=AUDIO_BLOCK,
                device=self.device_id,
                channels=AUDIO_CHANNELS,
                callback=self._audio_callback,
                latency=AUDIO_LATENCY
            )
            self.stream.start()
            print("[音频] 麦克风已启动")
            return True
        except Exception as e:
            print(f"[音频] 麦克风启动失败: {e}")
            self.running = False
            return False

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
            self.stream = None
        self.push_queue = None
        print("[音频] 已停止")

# ============================================================
# 主播流处理类
# ============================================================
# 分辨率探测结果缓存：避免每次重建 UI / 启动时都重新打开摄像头探测
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
        res = enumerate_camera_resolutions()
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
    return os.path.join(_app_dir(), "camres.json")


def _res_flag_path():
    """探测进行中标记：若启动时该文件仍存在，说明上次探测把进程搞崩了。"""
    return os.path.join(_app_dir(), "camres.probing")


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


def _probe_camera_resolutions_subprocess():
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
            cmd = [sys.executable, os.path.abspath(__file__), PROBE_ARG, tmpfile]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=CREATE_NO_WINDOW)
        try:
            proc.wait(timeout=30)
        except Exception:
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


def enumerate_camera_resolutions():
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

    res = _probe_camera_resolutions_subprocess()

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

    def _resolve_audio_device(self, auds):
        """根据已选麦克风设备，匹配 dshow 音频设备名。"""
        if self.audio_host.device_id is None:
            return auds[0] if auds else None
        try:
            name = sd.query_devices(self.audio_host.device_id)["name"]
        except Exception:
            return auds[0] if auds else None
        for d in auds:
            if name in d or d in name:
                return d
        return auds[0] if auds else name

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

    def _create_pusher(self):
        """根据运行环境自动选择推流后端：优先 PyAV（纯 Python），否则 ffmpeg。"""
        if HAVE_AV:
            p = PyAVRtmpPusher(
                RTMP_PUSH_URL, VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT,
                BASE_FPS, AUDIO_RATE, AUDIO_CHANNELS)
            p.on_state = self._on_push_state
            return p, "pyav"
        ffmpeg_exe = find_ffmpeg()
        if ffmpeg_exe is not None:
            p = FFmpegRtmpPusher(
                RTMP_PUSH_URL, VIRTUAL_CAM_WIDTH, VIRTUAL_CAM_HEIGHT,
                BASE_FPS, AUDIO_RATE, AUDIO_CHANNELS)
            vids, auds = list_dshow_devices()
            video_dev = vids[0] if vids else None
            audio_dev = self._resolve_audio_device(auds)
            p.configure_devices(video_dev, audio_dev,
                                beauty=(self.bright, self.contrast, self.sat))
            print(f"[主播] ffmpeg 推流：视频设备={video_dev}，音频设备={audio_dev}")
            return p, "ffmpeg"
        return None, None

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

    def start_streaming(self):
        if not self.camera_ready:
            print("[主播] 摄像头未就绪")
            return False
        # 0) 清理上一轮遗留的推流器（例如上次断流后未及时回收）
        if self.pusher is not None:
            self.stop_streaming()
        # 1) 选择推流后端
        self.pusher, self.push_backend = self._create_pusher()
        if self.pusher is None:
            self.push_error = "未找到可用的推流后端（需要安装 PyAV 或系统 ffmpeg）"
            print("[主播] " + self.push_error)
            return False
        # 2) 仅 PyAV 后端需要 Python 采集音频；ffmpeg 后端由 ffmpeg 直接采集
        if self.push_backend == "pyav":
            self.audio_host.set_push_queue(self.push_audio_queue)
            if not self.audio_host.start_mic_only():
                print("[主播] 警告：麦克风启动失败，将只推视频")
            else:
                print("[主播] 麦克风启动成功")
        else:
            print("[主播] ffmpeg 后端将自行采集音频，跳过 Python 麦克风采集")
        # 3) 启动推流
        audio_getter = self._pop_audio_chunk if self.push_backend == "pyav" else None
        ok = self.pusher.start(video_getter=self.produce_push_frame, audio_getter=audio_getter)
        if not ok:
            self.push_error = getattr(self.pusher, "error", "推流启动失败")
            print(f"[主播] 推流启动失败: {self.push_error}")
            self.pusher = None
            self.audio_host.stop()
            return False
        self.running = True
        self.push_state = "running"
        self.push_error = None
        print(f"[主播] RTMP 推流已启动（后端: {self.push_backend}）-> {RTMP_PUSH_URL}")
        return True

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
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.live_cap:
            self.live_cap.release()
            self.live_cap = None
        with QMutexLocker(self.mutex):
            self.cap_frame_queue.clear()
        print("[主播] 已停止")

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

# ============================================================
# 主窗口类
# ============================================================
class MainWin(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("智播豆")
        self.setFixedSize(1280, 720)
        self.setStyleSheet("""
            QMainWindow{background-color:#0b101a;}
            QWidget{background-color:#0b101a;color:#e6edf3;font-family:"Microsoft YaHei";}
            QLabel{color:#ccd6f6;}
            QPushButton{background:#1f2937;color:#2d88ff;border:1px solid #2d88ff;border-radius:6px;padding:5px;}
            QPushButton:disabled{background:#181818;color:#666666;border:1px solid #444444;}
            QCheckBox{color:#e6edf3;font-size:12px;}
            QSlider::groove:horizontal{background:#1f2937;height:6px;border-radius:3px;}
            QSlider::handle:horizontal{background:#2d88ff;width:14px;height:14px;border-radius:7px;}
            QComboBox{background:#1a2332;color:#e6edf3;border:1px solid #2d88ff;border-radius:4px;padding:3px;}
            QTextEdit{background:#1a2332;color:#e6edf3;border:1px solid #233554;border-radius:4px;}
            QFrame{background:#131a28;border:1px solid #233554;border-radius:8px;}
            QScrollArea{border:none;background:transparent;}
            QLineEdit{background:#1a2332;color:#00ccff;border:1px solid #2d88ff;border-radius:4px;padding:6px;font-size:13px;}
        """)

        self.local_phone = load_phone_config()
        self.host_stream = HostStream()
        self.client_stream = ClientStream()
        self.client_stream.frame_cb.connect(self.update_client)
        self.client_stream.auto_connected_sig.connect(self.on_auto_connected)
        self.host_stream.audio_host.vol_sig.connect(self.update_host_vol)

        self.timer = QTimer()
        self.timer.timeout.connect(self.pull_host_frame)
        self._last_push_state = "idle"   # 推流状态巡检用
        self.auth_timer = QTimer()
        self.auth_timer.timeout.connect(self.refresh_auth_status)
        self.auth_timer.start(1000)

        self.all_mics = get_all_mic_devices()
        self.all_speakers = get_all_speaker_devices()
        self.init_ui()

    def refresh_auth_status(self):
        auth_ok, remain_sec, total_days, max_client = get_auth_info()
        push_backend = self.host_stream.push_backend or "未启动"
        if auth_ok:
            days = remain_sec // DAY_SEC
            rem = remain_sec % DAY_SEC
            hours = rem // 3600
            rem %= 3600
            mins = rem // 60
            secs = rem % 60
            self.lab_auth_status.setText(
                f"状态: 已激活 | 剩余: {days}天 {hours:02d}时 {mins:02d}分 {secs:02d}秒\n推流后端: {push_backend}"
            )
            self.btn_start_host.setEnabled(True)
        else:
            self.lab_auth_status.setText("状态: 未激活")
            self.btn_start_host.setEnabled(False)

    def on_auto_connected(self, ip):
        QMessageBox.information(self, "自动连接", f"已连接到服务器: {ip}")

    def on_res_change(self, idx):
        w, h = self.res_combo.itemData(idx)
        self.host_stream.set_capture_resolution(w, h)

    def _on_res_probed(self, res):
        """分辨率后台探测完成：用真实支持的分辨率刷新下拉框（不影响正在进行的推流）。"""
        if not res or not hasattr(self, "res_combo") or self.res_combo is None:
            return
        cur = self.res_combo.currentData()
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        for (w, h) in res:
            orient = "竖屏" if h > w else "横屏"
            self.res_combo.addItem(f"{w}x{h} ({orient})", (w, h))
        idx = 0
        if cur in res:
            idx = res.index(cur)
        else:
            for _pref in [(720, 1280), (1280, 720)]:
                if _pref in res:
                    idx = res.index(_pref)
                    break
        self.res_combo.setCurrentIndex(idx)
        self.res_combo.blockSignals(False)
        # 仅当尚未开始推流时同步默认采集分辨率；推流中不打断摄像头
        if not self.timer.isActive():
            w, h = res[idx]
            self.host_stream.capture_w = w
            self.host_stream.capture_h = h

    def _on_res_probe_finished(self):
        """探测线程结束：先摘掉引用再安排销毁，避免留下悬空的 Python 包装器。"""
        t = getattr(self, "_res_probe", None)
        self._res_probe = None
        if t is not None:
            try:
                t.deleteLater()
            except Exception:
                pass

    def _wait_res_probe(self, timeout_ms=32000):
        """等待后台分辨率探测结束，避免探测子进程占着摄像头时与采集抢设备导致无预览。

        探测已改为独立子进程，耗时可能到数十秒，因此这里用 processEvents 轮询等待，
        保持界面可响应，而不是直接阻塞主线程。
        """
        t = getattr(self, "_res_probe", None)
        if t is None:
            return
        # 线程结束后 deleteLater 会销毁底层 C++ 对象，此时任何方法调用都会抛
        # RuntimeError；而 PyQt5 对槽函数内未捕获的异常默认直接 abort() 整个进程，
        # 表现就是"点一下按钮软件闪退且无任何日志"。这里必须逐次防御。
        def _alive_running(th):
            try:
                return th.isRunning()
            except RuntimeError:
                return False
            except Exception:
                return False

        if not _alive_running(t):
            self._res_probe = None
            return
        try:
            self.lab_host_preview.setText("正在检测摄像头支持的分辨率，请稍候…")
            QApplication.processEvents()
        except Exception:
            pass
        deadline = time.time() + timeout_ms / 1000.0
        while _alive_running(t) and time.time() < deadline:
            try:
                t.wait(100)
            except RuntimeError:
                break
            try:
                QApplication.processEvents()
            except Exception:
                pass

    def copy_machine_code(self):
        mc = get_machine_code()
        QApplication.clipboard().setText(mc)
        QMessageBox.information(self, "已复制", "机器码已复制到剪贴板!")

    def do_activate(self):
        try:
            phone = self.edit_phone.text().strip()
            code = self.license_edit.toPlainText().strip()
            if len(phone) != 11 or not phone.isdigit():
                QMessageBox.warning(self, "错误", "手机号必须是11位数字!")
                return
            if not code:
                QMessageBox.warning(self, "错误", "激活码不能为空!")
                return
            ok, msg = verify_and_save_activate_code(code, phone)
            if ok:
                CountDownDialog().exec_()
                self.refresh_auth_status()
                QMessageBox.information(self, "成功", "激活成功!")
            else:
                QMessageBox.warning(self, "失败", msg)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作失败: {str(e)}")

    def init_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # 首页
        home = QWidget()
        h_lay = QVBoxLayout(home)
        h_lay.setContentsMargins(50, 30, 50, 30)
        h_lay.setSpacing(20)

        lab_title = QLabel("智播豆")
        lab_title.setAlignment(Qt.AlignCenter)
        lab_title.setStyleSheet("font-size:32px;color:#00ccff;font-weight:bold;")
        h_lay.addWidget(lab_title)

        lab_subtitle = QLabel("高清直播推流系统")
        lab_subtitle.setAlignment(Qt.AlignCenter)
        lab_subtitle.setStyleSheet("font-size:16px;color:#8899bb;")
        h_lay.addWidget(lab_subtitle)

        h_lay.addSpacing(10)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_lay = QVBoxLayout(scroll_content)
        notice_text = """使用须知:
1. 本软件为音视频推流工具，仅供合法用途使用
2. 用户须遵守相关法律法规及平台政策
3. 软件授权一经售出，概不退款
4. 本软件不保证任何直播收益或效果
5. 使用本软件即表示同意以上条款"""
        lab_notice = QLabel(notice_text)
        lab_notice.setWordWrap(True)
        lab_notice.setStyleSheet("color:#bbbbbb;font-size:13px;line-height:1.8;")
        scroll_lay.addWidget(lab_notice)
        scroll_area.setWidget(scroll_content)
        scroll_area.setFixedHeight(180)
        h_lay.addWidget(scroll_area)

        phone_lay = QHBoxLayout()
        phone_lay.setSpacing(10)
        lab_phone_tip = QLabel("手机号码:")
        lab_phone_tip.setFixedWidth(100)
        lab_phone_tip.setStyleSheet("color:#00ccff;font-size:14px;")
        self.edit_phone = QLineEdit()
        self.edit_phone.setPlaceholderText("请输入11位手机号码")
        self.edit_phone.setText(self.local_phone)
        self.edit_phone.setStyleSheet("font-size:14px;")
        self.edit_phone.editingFinished.connect(self.on_phone_input_done)
        phone_lay.addWidget(lab_phone_tip)
        phone_lay.addWidget(self.edit_phone)
        h_lay.addLayout(phone_lay)

        self.check_agree = QCheckBox("我已阅读并同意以上所有条款")
        self.check_agree.setStyleSheet("font-size:13px;color:#e6edf3;")
        self.check_agree.stateChanged.connect(self.agree_state_change)
        h_lay.addWidget(self.check_agree, alignment=Qt.AlignCenter)

        h_lay.addSpacing(20)
        self.btn_host = QPushButton("进入主播模式")
        self.btn_client = QPushButton("进入观众模式")
        for btn in [self.btn_host, self.btn_client]:
            btn.setFixedSize(220, 50)
            btn.setStyleSheet("font-size:16px;font-weight:bold;")
            btn.setEnabled(False)
        self.btn_host.clicked.connect(self.enter_host_mode)
        self.btn_client.clicked.connect(self.enter_client_auto)
        h_lay.addWidget(self.btn_host, alignment=Qt.AlignCenter)
        h_lay.addWidget(self.btn_client, alignment=Qt.AlignCenter)
        h_lay.addStretch()
        self.stack.addWidget(home)

        # 主播页面
        host_page = QWidget()
        host_lay = QHBoxLayout(host_page)
        host_lay.setContentsMargins(15, 15, 15, 15)
        host_lay.setSpacing(12)

        left_host = QWidget()
        left_host.setFixedWidth(320)
        left_lay = QVBoxLayout(left_host)
        left_lay.setContentsMargins(12, 12, 12, 12)
        left_lay.setSpacing(10)

        self.btn_start_host = QPushButton("开始直播推流")
        self.btn_start_host.setFixedHeight(40)
        self.btn_start_host.setStyleSheet("font-size:15px;font-weight:bold;")
        self.btn_start_host.clicked.connect(self.toggle_host_cam)
        left_lay.addWidget(self.btn_start_host)

        self.lab_rtmp = QLabel(f"RTMP推流地址:\n{RTMP_PUSH_URL}")
        self.lab_rtmp.setWordWrap(True)
        self.lab_rtmp.setStyleSheet("font-size:11px;color:#00ccff;")
        left_lay.addWidget(self.lab_rtmp)

        left_lay.addWidget(QLabel("选择麦克风设备"))
        self.mic_combo = QComboBox()
        for dev_id, dev_name in self.all_mics:
            self.mic_combo.addItem(dev_name, dev_id)
        if self.all_mics:
            self.mic_combo.setCurrentIndex(0)
            self.host_stream.audio_host.set_mic_device(self.all_mics[0][0])
        self.mic_combo.currentIndexChanged.connect(
            lambda idx: self.host_stream.audio_host.set_mic_device(self.mic_combo.itemData(idx))
        )
        left_lay.addWidget(self.mic_combo)

        left_lay.addWidget(QLabel("麦克风音量"))
        self.host_vol_bar = VolumeBar()
        left_lay.addWidget(self.host_vol_bar)

        left_lay.addWidget(QLabel("麦克风增益"))
        self.mic_slider = QSlider(Qt.Horizontal)
        self.mic_slider.setRange(0, 100)
        self.mic_slider.setValue(50)
        self.mic_slider.valueChanged.connect(lambda v: self.host_stream.audio_host.set_mic_gain(v))
        left_lay.addWidget(self.mic_slider)

        left_lay.addWidget(QLabel("视频分辨率"))
        self.res_combo = QComboBox()
        # 先用静态列表填充，保证界面立即可用且不占用摄像头（避免启动时闪烁/卡顿）
        self._supported_res = get_cached_resolutions()
        for (w, h) in self._supported_res:
            orient = "竖屏" if h > w else "横屏"
            self.res_combo.addItem(f"{w}x{h} ({orient})", (w, h))
        # 默认值：优先竖屏 720p (720x1280)，其次横屏 1280x720，再退回第一个
        _preferred = [(720, 1280), (1280, 720)]
        _default_idx = 0
        for _pref in _preferred:
            if _pref in self._supported_res:
                _default_idx = self._supported_res.index(_pref)
                break
        self.res_combo.setCurrentIndex(_default_idx)
        self.res_combo.currentIndexChanged.connect(self.on_res_change)
        left_lay.addWidget(self.res_combo)

        # 让 HostStream 的采集分辨率与默认选项保持同步（此时摄像头尚未打开，仅记录）
        _dw, _dh = self._supported_res[_default_idx]
        self.host_stream.capture_w = _dw
        self.host_stream.capture_h = _dh

        # 后台异步探测摄像头真实支持的分辨率，完成后通过信号更新下拉框；
        # 这样启动/构建 UI 时不会在主线程同步打开摄像头，消除闪烁与卡顿
        self._res_probe = ResProbeThread()
        self._res_probe.done.connect(self._on_res_probed)
        # 注意：不能直接 finished -> deleteLater，否则 self._res_probe 会变成指向
        # 已销毁 C++ 对象的悬空包装器，后续 isRunning() 抛 RuntimeError，
        # 而 PyQt5 遇到槽内未捕获异常会直接 abort 进程（闪退且无日志）。
        self._res_probe.finished.connect(self._on_res_probe_finished)
        self._res_probe.start()

        left_lay.addWidget(QLabel("抖音直播间链接 (全局推流)"))
        self.host_live_input = QLineEdit()
        self.host_live_input.setPlaceholderText("粘贴抖音直播分享链接")
        left_lay.addWidget(self.host_live_input)
        host_parse_btn = QPushButton("解析线上流（作为推流画面源）")
        host_parse_btn.clicked.connect(self.on_host_parse_live)
        host_cam_btn = QPushButton("切回摄像头采集")
        host_cam_btn.clicked.connect(self.on_host_switch_cam)
        host_btn_lay = QHBoxLayout()
        host_btn_lay.addWidget(host_parse_btn)
        host_btn_lay.addWidget(host_cam_btn)
        left_lay.addLayout(host_btn_lay)
        left_lay.addSpacing(10)

        self.beauty_frame = QFrame()
        beauty_lay = QVBoxLayout(self.beauty_frame)
        beauty_lay.setContentsMargins(10, 10, 10, 10)
        beauty_lay.setSpacing(12)
        title_lab = QLabel("美颜调节")
        title_lab.setStyleSheet("color:#00ccff;font-size:14px;font-weight:bold;")
        beauty_lay.addWidget(title_lab)

        self.slid_br = QSlider(Qt.Horizontal)
        self.slid_br.setRange(0, 100)
        self.slid_br.setValue(50)
        self.slid_br.valueChanged.connect(lambda v: setattr(self.host_stream, "bright", v))
        beauty_lay.addWidget(QLabel("亮度"))
        beauty_lay.addWidget(self.slid_br)

        self.slid_ct = QSlider(Qt.Horizontal)
        self.slid_ct.setRange(0, 100)
        self.slid_ct.setValue(50)
        self.slid_ct.valueChanged.connect(lambda v: setattr(self.host_stream, "contrast", v))
        beauty_lay.addWidget(QLabel("对比度"))
        beauty_lay.addWidget(self.slid_ct)

        self.slid_st = QSlider(Qt.Horizontal)
        self.slid_st.setRange(0, 100)
        self.slid_st.setValue(50)
        self.slid_st.valueChanged.connect(lambda v: setattr(self.host_stream, "sat", v))
        beauty_lay.addWidget(QLabel("饱和度"))
        beauty_lay.addWidget(self.slid_st)

        self.slid_sh = QSlider(Qt.Horizontal)
        self.slid_sh.setRange(0, 100)
        self.slid_sh.setValue(50)
        self.slid_sh.valueChanged.connect(lambda v: setattr(self.host_stream, "sharp", v))
        beauty_lay.addWidget(QLabel("锐度"))
        beauty_lay.addWidget(self.slid_sh)
        left_lay.addWidget(self.beauty_frame)

        self.auth_frame = QFrame()
        auth_lay = QVBoxLayout(self.auth_frame)
        self.lab_auth_status = QLabel("状态: 未激活")
        self.lab_auth_status.setWordWrap(True)
        self.lab_auth_status.setStyleSheet("font-size:13px;")
        self.lab_mc = QLabel(f"机器码: {get_machine_code()}")
        self.lab_mc.setStyleSheet("font-size:12px;color:#8899bb;")
        btn_copy_mc = QPushButton("复制机器码")
        btn_copy_mc.clicked.connect(self.copy_machine_code)
        self.license_edit = QTextEdit()
        self.license_edit.setFixedHeight(35)
        self.license_edit.setPlaceholderText("请输入激活码")
        btn_act = QPushButton("激活授权")
        btn_act.clicked.connect(self.do_activate)
        auth_lay.addWidget(self.lab_auth_status)
        auth_lay.addWidget(self.lab_mc)
        auth_lay.addWidget(btn_copy_mc)
        auth_lay.addWidget(self.license_edit)
        auth_lay.addWidget(btn_act)
        left_lay.addWidget(self.auth_frame)
        # 移除 stretch：左侧内容已超出窗口高度，改为用 QScrollArea 滚动，避免组件被压缩

        btn_back_h = QPushButton("返回首页")
        btn_back_h.setFixedHeight(30)
        btn_back_h.clicked.connect(self.return_home)
        left_lay.addWidget(btn_back_h)

        right_host = QWidget()
        right_lay = QVBoxLayout(right_host)
        right_lay.setAlignment(Qt.AlignCenter)
        self.lab_host_preview = QLabel("预览画面")
        self.lab_host_preview.setFixedSize(360, 640)
        self.lab_host_preview.setStyleSheet("border:2px solid #2d88ff;background:#000;color:#888;border-radius:8px;font-size:16px;")
        self.lab_host_preview.setAlignment(Qt.AlignCenter)
        right_lay.addWidget(self.lab_host_preview)

        # 左侧控制面板内容过多，加入滚动区域防止组件被压缩/截断
        # 用 QFrame 做视觉外框，QScrollArea 放在里面，让滚动条看起来是面板的一部分
        host_scroll = QScrollArea()
        host_scroll.setWidget(left_host)
        host_scroll.setWidgetResizable(True)
        host_scroll.setFrameShape(QScrollArea.NoFrame)
        host_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host_scroll.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 4px 4px 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2d88ff;
                min-height: 40px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        left_host_panel = QFrame()
        left_host_panel.setFixedWidth(328)
        left_host_panel_lay = QVBoxLayout(left_host_panel)
        left_host_panel_lay.setContentsMargins(0, 0, 0, 0)
        left_host_panel_lay.addWidget(host_scroll)
        host_lay.addWidget(left_host_panel)
        host_lay.addWidget(right_host)
        self.stack.addWidget(host_page)

        # 观众页面
        client_page = QWidget()
        client_lay = QHBoxLayout(client_page)
        client_lay.setContentsMargins(15, 15, 15, 15)
        client_lay.setSpacing(12)

        left_client = QWidget()
        left_client.setFixedWidth(320)
        leftc_lay = QVBoxLayout(left_client)
        leftc_lay.setContentsMargins(12, 12, 12, 12)
        leftc_lay.setSpacing(10)

        self.tip_auto = QLabel(f"正在连接服务器 {RELAY_SERVER_IP}:{RELAY_CLIENT_VIDEO_PORT}...")
        self.tip_auto.setStyleSheet("color:#00ff99;font-size:14px;font-weight:bold;")
        leftc_lay.addWidget(self.tip_auto)

        leftc_lay.addWidget(QLabel("子机独立解析（仅本机生效）"))
        self.client_live_input = QLineEdit()
        self.client_live_input.setPlaceholderText("粘贴抖音链接，本地单独拉流")
        leftc_lay.addWidget(self.client_live_input)
        client_parse_btn = QPushButton("启动本地直播流")
        client_parse_btn.clicked.connect(self.on_client_local_parse)
        leftc_lay.addWidget(client_parse_btn)
        leftc_lay.addSpacing(10)

        leftc_lay.addWidget(QLabel("=== 云服务器拉流 ==="))
        leftc_lay.addWidget(QLabel(f"服务器IP: {RELAY_SERVER_IP}"))
        leftc_lay.addWidget(QLabel(f"视频端口: {RELAY_CLIENT_VIDEO_PORT}"))
        leftc_lay.addWidget(QLabel(f"音频端口: {RELAY_CLIENT_AUDIO_PORT}"))

        leftc_lay.addWidget(QLabel(""))
        leftc_lay.addWidget(QLabel("选择扬声器设备"))
        self.speaker_combo = QComboBox()
        for dev_id, dev_name in self.all_speakers:
            self.speaker_combo.addItem(dev_name, dev_id)
        if self.all_speakers:
            self.speaker_combo.setCurrentIndex(0)
            self.client_stream.audio_client.set_speaker_device(self.speaker_combo.itemData(0))
        self.speaker_combo.currentIndexChanged.connect(
            lambda idx: self.client_stream.audio_client.set_speaker_device(self.speaker_combo.itemData(idx))
        )
        leftc_lay.addWidget(self.speaker_combo)

        leftc_lay.addWidget(QLabel("音频音量"))
        self.client_vol_bar = VolumeBar()
        leftc_lay.addWidget(self.client_vol_bar)

        self.client_beauty_frame = QFrame()
        client_beauty_lay = QVBoxLayout(self.client_beauty_frame)
        client_beauty_lay.setContentsMargins(10, 10, 10, 10)
        client_beauty_lay.setSpacing(12)
        client_title_lab = QLabel("观众美颜调节")
        client_title_lab.setStyleSheet("color:#00ccff;font-size:14px;font-weight:bold;")
        client_beauty_lay.addWidget(client_title_lab)

        self.c_br = QSlider(Qt.Horizontal)
        self.c_br.setRange(0, 100)
        self.c_br.setValue(50)
        self.c_br.valueChanged.connect(lambda v: setattr(self.client_stream, "bright", v))
        client_beauty_lay.addWidget(QLabel("亮度"))
        client_beauty_lay.addWidget(self.c_br)

        self.c_ct = QSlider(Qt.Horizontal)
        self.c_ct.setRange(0, 100)
        self.c_ct.setValue(50)
        self.c_ct.valueChanged.connect(lambda v: setattr(self.client_stream, "contrast", v))
        client_beauty_lay.addWidget(QLabel("对比度"))
        client_beauty_lay.addWidget(self.c_ct)

        self.c_st = QSlider(Qt.Horizontal)
        self.c_st.setRange(0, 100)
        self.c_st.setValue(50)
        self.c_st.valueChanged.connect(lambda v: setattr(self.client_stream, "sat", v))
        client_beauty_lay.addWidget(QLabel("饱和度"))
        client_beauty_lay.addWidget(self.c_st)

        self.c_sh = QSlider(Qt.Horizontal)
        self.c_sh.setRange(0, 100)
        self.c_sh.setValue(50)
        self.c_sh.valueChanged.connect(lambda v: setattr(self.client_stream, "sharp", v))
        client_beauty_lay.addWidget(QLabel("锐度"))
        client_beauty_lay.addWidget(self.c_sh)
        leftc_lay.addWidget(self.client_beauty_frame)

        leftc_lay.addWidget(QLabel("输出音量"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(82)
        self.vol_slider.valueChanged.connect(self.client_stream.audio_client.set_volume)
        leftc_lay.addWidget(self.vol_slider)
        # 同主播页：移除 stretch，由 QScrollArea 处理溢出

        btn_back_c = QPushButton("返回首页")
        btn_back_c.setFixedHeight(30)
        btn_back_c.clicked.connect(self.return_home)
        leftc_lay.addWidget(btn_back_c)

        right_client = QWidget()
        right_layc = QVBoxLayout(right_client)
        right_layc.setAlignment(Qt.AlignCenter)
        self.lab_client_preview = QLabel("等待连接...")
        self.lab_client_preview.setFixedSize(360, 640)
        self.lab_client_preview.setStyleSheet("border:2px solid #2d88ff;background:#000;color:#888;border-radius:8px;font-size:16px;")
        self.lab_client_preview.setAlignment(Qt.AlignCenter)
        right_layc.addWidget(self.lab_client_preview)

        # 观众页左侧同样加入滚动区域
        client_scroll = QScrollArea()
        client_scroll.setWidget(left_client)
        client_scroll.setWidgetResizable(True)
        client_scroll.setFrameShape(QScrollArea.NoFrame)
        client_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        client_scroll.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 4px 4px 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2d88ff;
                min-height: 40px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        left_client_panel = QFrame()
        left_client_panel.setFixedWidth(328)
        left_client_panel_lay = QVBoxLayout(left_client_panel)
        left_client_panel_lay.setContentsMargins(0, 0, 0, 0)
        left_client_panel_lay.addWidget(client_scroll)
        client_lay.addWidget(left_client_panel)
        client_lay.addWidget(right_client)
        self.stack.addWidget(client_page)

        self.client_stream.audio_client.vol_sig.connect(self.client_vol_bar.set_vol)

    def on_host_parse_live(self):
        url = self.host_live_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入抖音直播间链接！")
            return
        auth_ok, _, _, _ = get_auth_info()
        if not auth_ok:
            QMessageBox.warning(self, "错误", "未授权或授权已过期!")
            return
        # 若正在推流，先停推流（保留摄像头）
        if self.host_stream.running:
            self.host_stream.stop_streaming()
            self.btn_start_host.setText("开始直播推流")
        ok = self.host_stream.set_live_source(url)
        if ok:
            self._ensure_host_preview()
            if not self.host_stream.camera_ready:
                QMessageBox.critical(self, "错误", "直播源启动失败！")
                return
            if not self.host_stream.start_streaming():
                QMessageBox.critical(self, "错误", "推流服务启动失败！")
                return
            self.btn_start_host.setText("停止直播推流")
            QMessageBox.information(self, "成功", "已切换线上直播源，将作为 RTMP 推流画面")
        else:
            QMessageBox.critical(self, "失败", "链接解析失败，请检查链接有效性")

    def on_host_switch_cam(self):
        if self.host_stream.running:
            self.host_stream.stop_streaming()
            self.btn_start_host.setText("开始直播推流")
        self.host_stream.set_cam_source()
        self._ensure_host_preview()
        QMessageBox.information(self, "切换", "已切回摄像头采集")

    def on_client_local_parse(self):
        url = self.client_live_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入直播间链接！")
            return
        ok = self.client_stream.start_local_live_stream(url)
        if ok:
            self.tip_auto.setText("本地独立拉流中（不经过云服务器）")
            QMessageBox.information(self, "成功", "子机本地独立拉流生效，仅本机虚拟摄像头输出")
        else:
            QMessageBox.critical(self, "失败", "链接解析失败，请检查链接有效性")

    def enter_client_auto(self):
        self.stack.setCurrentIndex(2)
        self.client_stream.auto_find_and_connect()

    def on_phone_input_done(self):
        phone = self.edit_phone.text().strip()
        save_phone_config(phone)
        self.local_phone = phone

    def agree_state_change(self):
        checked = self.check_agree.isChecked()
        self.btn_host.setEnabled(checked)
        self.btn_client.setEnabled(checked)

    def enter_host_mode(self):
        """进入主播模式：打开摄像头预览（不要求授权，推流时才校验），预览画面立即可见。"""
        self.stack.setCurrentIndex(1)
        try:
            self._ensure_host_preview()
        except Exception:
            import traceback as _tb
            _report_fatal("进入主播模式", _tb.format_exc())

    def _ensure_host_preview(self):
        """确保摄像头预览已开启：相机未就绪则打开；预览定时器始终运行（与推流解耦）。"""
        if self.timer.isActive():
            return
        self._wait_res_probe()
        if not self.host_stream.camera_ready:
            ok = False
            try:
                ok = self.host_stream.init_camera_only()
            except Exception as e:
                print(f"[主界面] 摄像头初始化异常: {e}")
            if not ok:
                self.lab_host_preview.setText("摄像头未就绪\n请检查设备是否被其他程序占用")
                QMessageBox.critical(self, "错误",
                                     "摄像头启动失败，请检查设备是否被其他程序占用！")
                return
        self.timer.start(55)

    def return_home(self):
        """返回首页：停止推流与预览、释放摄像头与观众端资源。"""
        self.timer.stop()
        self.host_stream.stop_streaming()
        self.host_stream.stop()
        self.client_stream.stop()
        self.lab_host_preview.clear()
        self.lab_host_preview.setText("预览画面")
        self.lab_client_preview.clear()
        self.lab_client_preview.setText("等待连接...")
        self.stack.setCurrentIndex(0)

    def toggle_host_cam(self):
        auth_ok, _, _, _ = get_auth_info()
        if not auth_ok:
            QMessageBox.warning(self, "错误", "未授权或授权已过期!")
            return
        if not self.host_stream.running:
            # 确保预览已开启（摄像头已打开），再启动推流
            self._ensure_host_preview()
            if not self.host_stream.camera_ready:
                QMessageBox.critical(self, "错误", "摄像头或直播源启动失败，请检查设备！")
                return
            if not self.host_stream.start_streaming():
                QMessageBox.critical(self, "错误", "推流服务启动失败!")
                return
            self.btn_start_host.setText("停止直播推流")
            backend = self.host_stream.push_backend or "未知"
            self.lab_rtmp.setText(f"RTMP推流中（后端:{backend}）:\n{RTMP_PUSH_URL}")
        else:
            # 停止推流，但保留摄像头与预览画面
            self.host_stream.stop_streaming()
            self.btn_start_host.setText("开始直播推流")
            self.lab_rtmp.setText(f"RTMP推流地址:\n{RTMP_PUSH_URL}")

    def update_host_vol(self, vol):
        self.host_vol_bar.set_vol(vol)

    def _check_push_state(self):
        """预览定时器顺带巡检推流状态：重连中提示、彻底断流则复位按钮。"""
        st = getattr(self.host_stream, "push_state", "idle")
        if st == self._last_push_state:
            return
        self._last_push_state = st
        if st == "reconnecting":
            self.lab_rtmp.setText(f"RTMP 连接中断，正在重连…\n{RTMP_PUSH_URL}")
        elif st == "running":
            backend = self.host_stream.push_backend or "未知"
            self.lab_rtmp.setText(f"RTMP推流中（后端:{backend}）:\n{RTMP_PUSH_URL}")
        elif st == "fatal":
            err = self.host_stream.push_error or "连接中断"
            self.host_stream.stop_streaming()
            self._last_push_state = "idle"
            self.btn_start_host.setText("开始直播推流")
            self.lab_rtmp.setText(f"RTMP推流地址:\n{RTMP_PUSH_URL}")
            QMessageBox.warning(
                self, "推流已断开",
                f"RTMP 推流中断且重连失败：\n{err}\n\n"
                f"常见原因：\n"
                f"1) 上行带宽不足以承载 {RTMP_VIDEO_BITRATE // 1000} kbps，可下调码率或分辨率\n"
                f"2) 服务器 {RTMP_SERVER_IP}:{RTMP_PORT} 不可达或已拒绝推流\n"
                f"3) 网络防火墙/NAT 掐断了长连接\n\n"
                f"预览画面不受影响，可稍后重新点击「开始直播推流」。")

    def pull_host_frame(self):
        try:
            self._check_push_state()
            frame = self.host_stream.get_latest_frame()
            if frame is None:
                return
            br = self.slid_br.value()
            ct = self.slid_ct.value()
            st = self.slid_st.value()
            sh = self.slid_sh.value()
            send_frame = beauty_process(frame, br, ct, st, sh)
            send_frame = crop_to_portrait(send_frame)
            pw = max(2, self.lab_host_preview.width())
            ph = max(2, self.lab_host_preview.height())
            send_frame = cv2.resize(send_frame, (pw, ph), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(send_frame, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, pw, ph, pw * 3, QImage.Format_RGB888)
            self.lab_host_preview.setPixmap(QPixmap.fromImage(qimg))
        except Exception as e:
            if not getattr(self, "_pull_err", False):
                self._pull_err = True
                print(f"[预览] pull_host_frame 异常: {e}")

    def update_client(self, frame):
        if frame is None:
            return
        pre_w, pre_h = self.lab_client_preview.width(), self.lab_client_preview.height()
        disp = cv2.resize(frame, (pre_w, pre_h), cv2.INTER_CUBIC)
        disp_rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        qt_img = QImage(disp_rgb.data, pre_w, pre_h, pre_w * 3, QImage.Format_RGB888)
        self.lab_client_preview.setPixmap(QPixmap.fromImage(qt_img))

    def closeEvent(self, event):
        self.host_stream.stop()
        self.client_stream.stop()
        event.accept()

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
                _log = os.path.join(_app_dir(), "crash.log")
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


def _report_fatal(stage, exc_text):
    """启动阶段的致命错误：写日志 + 尽力弹窗，避免打包后“双击没反应”。"""
    print(f"[FATAL] {stage} 失败:\n{exc_text}")
    try:
        with open(os.path.join(_app_dir(), "crash.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + f" [{stage}]\n" + exc_text + "\n\n")
    except Exception:
        pass
    try:
        QMessageBox.critical(None, "启动失败",
                             f"{stage} 失败，详情已写入 crash.log：\n\n" + exc_text[-1500:])
    except Exception:
        pass


def _install_excepthook():
    """PyQt5 对槽函数内未捕获的 Python 异常会直接 qFatal/abort 整个进程——
    表现为"点一下按钮就闪退，没有弹窗也没有日志"。abort 无法阻止，但 PyQt5 在
    abort 前会先走 sys.excepthook，因此这里挂钩子把现场落盘，保证有据可查。"""
    import traceback as _tb

    _prev = sys.excepthook

    def _hook(etype, value, tb):
        try:
            text = "".join(_tb.format_exception(etype, value, tb))
            with open(os.path.join(_app_dir(), "crash.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " [未捕获异常]\n" + text + "\n\n")
            print("[FATAL] 未捕获异常:\n" + text)
        except Exception:
            pass
        try:
            _prev(etype, value, tb)
        except Exception:
            pass

    sys.excepthook = _hook


if __name__ == "__main__":
    # 打包后若使用 multiprocessing，子进程会重新执行入口脚本导致无限开窗，必须先声明
    import multiprocessing
    multiprocessing.freeze_support()

    # 分辨率探测 worker 模式：主程序以 `<exe> --probe-cam <outfile>` 自调用时，
    # 只跑摄像头探测并把结果写入文件后立即退出，绝不创建任何界面。
    # 这样即使摄像头驱动在探测中触发 C 层崩溃，死的也只是这个子进程。
    # 必须放在创建 QApplication 之前。
    if PROBE_ARG in sys.argv:
        _i = sys.argv.index(PROBE_ARG)
        _out = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else ""
        run_probe_worker(_out)
        sys.exit(0)  # run_probe_worker 内部已 os._exit，此行仅作兜底

    import traceback as _tb
    _install_excepthook()
    app = SafeApplication(sys.argv)
    try:
        win = MainWin()
        win.show()
    except Exception:
        # 主窗口构造期的异常不在 Qt 事件循环内，SafeApplication.notify 兜不住
        _report_fatal("主窗口初始化", _tb.format_exc())
        sys.exit(1)
    sys.exit(app.exec_())