# -*- coding: utf-8 -*-
"""全局配置与常量。

只依赖标准库，不 import 项目内任何模块 —— 保证任何模块都能安全引用配置，
不会形成循环导入。想改推流地址 / 码率 / 分辨率，只改这个文件。
"""
import os


APP_VERSION = "1.7.0"


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
RTMP_SERVER_IP = "43.248.187.207"
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

# 画面来源类型
SOURCE_TYPE_CAM = "camera"
SOURCE_TYPE_LIVE = "live"

# 分辨率探测 worker 的命令行开关：exe 以该参数自调用时只探测、不启动界面
PROBE_ARG = "--probe-cam"

# 打包自检开关：exe 以该参数启动时逐个 import 全部项目模块并打印结果，用于
# 验证打包产物（尤其是 PYZ 归档）是否完整，不启动界面
SELFCHECK_ARG = "--selfcheck"

# ============================================================
# 项目模块清单（按功能划分的包）
# ============================================================
# 仅记录模块名，不做导入 —— 供 --selfcheck 自检遍历，以及打包脚本对照目录结构。
# 新增模块时记得同步这里，否则打包能过（静态分析追踪得到）但自检覆盖不到。
PROJECT_PACKAGES = ("core", "capture", "processing", "streaming",
                    "sessions", "licensing", "pdk", "ui", "ui.panels")
PROJECT_MODULES = (
    "core.config", "core.runtime", "core.diagnostics", "core.net",
    "core.credentials",
    "capture.devices", "capture.audio", "capture.resolution",
    "processing.image", "processing.live",
    "streaming.ffmpeg_tool", "streaming.pyav_pusher",
    "streaming.ffmpeg_pusher", "streaming.factory",
    "sessions.host", "sessions.client",
    "licensing.auth",
    "pdk.pdk_client", "pdk.auth_service",
    "ui.widgets", "ui.app", "ui.theme", "ui.icons", "ui.brand_banner",
    "ui.login_window", "ui.main_window",
    "ui.panels.base", "ui.panels.home", "ui.panels.auth",
    "ui.panels.host", "ui.panels.client",
)
