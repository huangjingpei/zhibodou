# -*- coding: utf-8 -*-
"""观众面板：观众页（左控制区 + 右预览）的全部控件与交互。

含：云服务器自动连接提示、本地独立拉流解析、扬声器选择/音量、观众端美颜调节。
拉流帧通过 client_stream.frame_cb 信号回调到 update_client 渲染到预览。
"""
import cv2
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QSlider, QFrame, QScrollArea,
)
from core.config import (RELAY_SERVER_IP, RELAY_CLIENT_VIDEO_PORT, RELAY_CLIENT_AUDIO_PORT)
from ui.widgets import VolumeBar
from ui.panels.base import Panel


class ClientPanel(Panel):
    def __init__(self, win):
        super().__init__(win)
        self.client_stream = win.client_stream

    def build(self, parent):
        client_page = QWidget(parent)
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
        client_parse_btn.clicked.connect(self.on_local_parse)
        leftc_lay.addWidget(client_parse_btn)
        leftc_lay.addSpacing(10)

        leftc_lay.addWidget(QLabel("=== 云服务器拉流 ==="))
        leftc_lay.addWidget(QLabel(f"服务器IP: {RELAY_SERVER_IP}"))
        leftc_lay.addWidget(QLabel(f"视频端口: {RELAY_CLIENT_VIDEO_PORT}"))
        leftc_lay.addWidget(QLabel(f"音频端口: {RELAY_CLIENT_AUDIO_PORT}"))

        leftc_lay.addWidget(QLabel(""))
        leftc_lay.addWidget(QLabel("选择扬声器设备"))
        self.speaker_combo = QComboBox()
        for dev_id, dev_name in self.win.all_speakers:
            self.speaker_combo.addItem(dev_name, dev_id)
        if self.win.all_speakers:
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
        btn_back_c.clicked.connect(self.win.return_home)
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

        # 拉流帧 / 自动连接信号回调（原在 MainWin.__init__ 中连接，现随面板构建）
        self.client_stream.frame_cb.connect(self.update_client)
        self.client_stream.auto_connected_sig.connect(self.on_auto_connected)
        self.client_stream.audio_client.vol_sig.connect(self.client_vol_bar.set_vol)
        return client_page

    def on_local_parse(self):
        from PyQt5.QtWidgets import QMessageBox
        url = self.client_live_input.text().strip()
        if not url:
            QMessageBox.warning(self.lab_client_preview, "提示", "请输入直播间链接！")
            return
        ok = self.client_stream.start_local_live_stream(url)
        if ok:
            self.tip_auto.setText("本地独立拉流中（不经过云服务器）")
            QMessageBox.information(self.lab_client_preview, "成功", "子机本地独立拉流生效，仅本机虚拟摄像头输出")
        else:
            QMessageBox.critical(self.lab_client_preview, "失败", "链接解析失败，请检查链接有效性")

    def on_auto_connected(self, ip):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self.lab_client_preview, "自动连接", f"已连接到服务器: {ip}")

    def update_client(self, frame):
        if frame is None:
            return
        pre_w, pre_h = self.lab_client_preview.width(), self.lab_client_preview.height()
        disp = cv2.resize(frame, (pre_w, pre_h), cv2.INTER_CUBIC)
        disp_rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        qt_img = QImage(disp_rgb.data, pre_w, pre_h, pre_w * 3, QImage.Format_RGB888)
        self.lab_client_preview.setPixmap(QPixmap.fromImage(qt_img))

    def reset_preview(self):
        """返回首页时清空并复位观众预览（由 MainWin.return_home 调用）。"""
        self.lab_client_preview.clear()
        self.lab_client_preview.setText("等待连接...")
