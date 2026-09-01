# -*- coding: utf-8 -*-
"""主窗口：首页 / 主播页 / 观众页三页切换。

只负责界面与交互，所有业务逻辑都在 sessions / streaming / capture 里。
"""
import time

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QSlider, QCheckBox,
    QComboBox, QMessageBox, QFrame, QLineEdit, QTextEdit, QScrollArea,
)

from capture.devices import get_all_mic_devices, get_all_speaker_devices
from capture.resolution import get_cached_resolutions, ResProbeThread
from core.config import (DAY_SEC, RTMP_PUSH_URL, RTMP_VIDEO_BITRATE,
                         RTMP_SERVER_IP, RTMP_PORT,
                         RELAY_SERVER_IP, RELAY_CLIENT_VIDEO_PORT,
                         RELAY_CLIENT_AUDIO_PORT)
from core.diagnostics import report_fatal
from licensing.auth import (get_auth_info, verify_and_save_activate_code,
                            save_phone_config, load_phone_config,
                            get_machine_code)
from processing.image import crop_to_portrait, beauty_process
from sessions.client import ClientStream
from sessions.host import HostStream
from ui.widgets import CountDownDialog, VolumeBar


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
            report_fatal("进入主播模式", _tb.format_exc())

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
