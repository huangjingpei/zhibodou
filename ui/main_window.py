# -*- coding: utf-8 -*-
"""主窗口编排器：组合首页 / 主播 / 观众三个页面（各自对应 ui.panels 子面板），
负责页面导航、定时器与生命周期，不再直接持有任何控件。

具体控件与交互逻辑分散在：
  ui/panels/home.py   — 首页面板
  ui/panels/host.py   — 主播面板（含内嵌 ui/panels/auth.py 授权面板）
  ui/panels/client.py  — 观众面板
业务逻辑一律在 sessions / streaming / capture，本文件只做编排。
"""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMainWindow, QStackedWidget

from capture.devices import get_all_mic_devices, get_all_speaker_devices
from core.diagnostics import report_fatal
from licensing.auth import load_phone_config
from sessions.client import ClientStream
from sessions.host import HostStream
from ui.panels.home import HomePanel
from ui.panels.host import HostPanel
from ui.panels.client import ClientPanel


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

        # 预览定时器须先于面板创建：HostPanel.__init__ 会持有它
        self.timer = QTimer()

        # 面板（build 在 init_ui 中调用，届时互相引用才需要）
        self.home_panel = HomePanel(self)
        self.host_panel = HostPanel(self)
        self.client_panel = ClientPanel(self)

        # 预览定时器：超时回调交由主播面板渲染预览帧 + 巡检推流状态
        self.timer.timeout.connect(self.host_panel.pull_frame)

        # 授权状态巡检定时器：超时回调交由主播页内嵌的授权面板刷新
        self.auth_timer = QTimer()
        self.auth_timer.start(1000)

        self.all_mics = get_all_mic_devices()
        self.all_speakers = get_all_speaker_devices()
        self.init_ui()

    def init_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.addWidget(self.home_panel.build(self.stack))
        self.stack.addWidget(self.host_panel.build(self.stack))
        self.stack.addWidget(self.client_panel.build(self.stack))
        # 授权面板在主播页 build 时才创建，故在此连接其刷新回调
        self.auth_timer.timeout.connect(self.host_panel.auth_panel.refresh_status)

    # ---------------------------------------------------------------- 页面导航
    def enter_host_mode(self):
        """进入主播模式：打开摄像头预览（不要求授权，推流时才校验），预览画面立即可见。"""
        self.stack.setCurrentIndex(1)
        try:
            self.host_panel.ensure_preview()
        except Exception:
            import traceback as _tb
            report_fatal("进入主播模式", _tb.format_exc())

    def enter_client_auto(self):
        self.stack.setCurrentIndex(2)
        self.client_stream.auto_find_and_connect()

    def return_home(self):
        """返回首页：停止推流与预览、释放摄像头与观众端资源。"""
        self.timer.stop()
        self.host_stream.stop_streaming()
        self.host_stream.stop()
        self.client_stream.stop()
        self.host_panel.reset_preview()
        self.client_panel.reset_preview()
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        self.host_stream.stop()
        self.client_stream.stop()
        event.accept()
