# -*- coding: utf-8 -*-
"""智播豆桌面端统一视觉系统（PyQt5 版）。

与 zhibodou-ai 项目 `src/gui/theme.py` + `src/gui/login.py` 的视觉令牌保持
一致：同一套深海蓝配色、同一套字体层级。改这里即可全局生效，各面板**不要**
再内联写死颜色与字号。

字号单位说明
------------
参考项目（Tkinter）的字号是 **pt**。Qt 的 QSS 同样支持 `pt` 单位，因此这里
直接沿用相同数值，而不是换算成 px —— 换算会引入 DPI 误差，导致两个项目实际
观感不一致。
"""
from PyQt5.QtGui import QColor, QFont, QFontDatabase

# ====================== 色板（与参考项目逐值对齐） ======================
BG = "#080F1C"            # 全局最底层背景
BG_ELEVATED = "#0B1422"   # 略微抬升的背景
SURFACE = "#111C2B"       # 卡片 / 面板
SURFACE_ALT = "#162538"   # 文本域
SURFACE_SOFT = "#1B2D43"  # 输入框
BORDER = "#34485F"
BORDER_FOCUS = "#7F98FF"

TEXT = "#FFFFFF"
TEXT_SOFT = "#E7EDF5"
TEXT_MUTED = "#AFBED0"
TEXT_FAINT = "#7F91A6"

PRIMARY = "#6D86F7"
PRIMARY_HOVER = "#8299FF"
CYAN = "#43C7D8"
TEAL = "#36C5A3"
GREEN = "#42D392"
AMBER = "#F4BC68"
RED = "#F16A78"
RED_DARK = "#CF4F61"
PURPLE = "#AA91F6"

# banner 渐变（左侧品牌区）
BANNER_DARK = "#27346F"
BANNER_MID = "#315DC7"
BANNER_LIGHT = "#176F9C"
BANNER_TEXT = "#FFFFFF"
BANNER_SUB = "#D7E8FF"
BANNER_FAINT = "#9ECFE0"

# ====================== 字体层级（Typography Scale） ======================
# 靠「字号 + 字重 + 颜色」三重梯度建立层次，从强到弱 7 级。
FS_DISPLAY = 28   # banner 项目名 —— 最强视觉焦点
FS_H1 = 22        # 页面主标题
FS_H2 = 14        # tab 标签 / 区块标题
FS_BODY = 13      # 输入框正文（中文可读性下限）
FS_CAPTION = 12   # 副标题 / 辅助说明
FS_SMALL = 11     # 复选框 / 链接 / 版本号
FS_TINY = 9       # 版权等最弱信息

_CN_FONT_CANDIDATES = (
    "Microsoft YaHei UI",   # 首选：为 UI 优化，行高更小、字距更紧
    "微软雅黑",
    "Microsoft YaHei",
    "PingFang SC",
    "SimHei",
)
FONT_EN = "Segoe UI"
_cn_font_cache = None


def cn_font_family():
    """挑选系统里真实存在的中文字体（带缓存）。

    与参考项目同样采取「惰性求值」：`QFontDatabase` 需要 QApplication 已存在，
    而本模块通常在 QApplication 之前被 import。若在模块级求值会拿不到字体列表，
    静默退化成默认字体 —— 真机上明明有雅黑却用不上。
    """
    global _cn_font_cache
    if _cn_font_cache:
        return _cn_font_cache
    try:
        families = set(QFontDatabase().families())
    except Exception:
        families = set()
    if not families:
        # QApplication 尚未建立。**绝不缓存**兜底值，否则会把兜底永久固化，
        # 后面即使 app 就绪也用不上真正的雅黑。
        return "Microsoft YaHei"
    for name in _CN_FONT_CANDIDATES:
        if name in families:
            _cn_font_cache = name
            return name
    return "Microsoft YaHei"


def font(size, bold=False, family=None, underline=False):
    """构造 QFont，统一入口，避免散落的字号魔法数字。size 单位为 pt。"""
    f = QFont(family or cn_font_family())
    f.setPointSize(size)
    f.setBold(bold)
    if underline:
        f.setUnderline(True)
    return f


def font_en(size, bold=False):
    return font(size, bold=bold, family=FONT_EN)


def mix_hex(start, end, t):
    """在两个 #rrggbb 之间线性插值，用于渐变。"""
    a = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def shade(hex_color, factor):
    """按 factor 缩放亮度（>1 变亮，<1 变暗），用于 hover / pressed 反馈。"""
    s = hex_color.lstrip("#")
    r, g, b = (int(s[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (
        max(0, min(255, int(r * factor))),
        max(0, min(255, int(g * factor))),
        max(0, min(255, int(b * factor))),
    )


def qcolor(hex_color, alpha=255):
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


# ====================== 全局 QSS ======================
def app_qss():
    """返回全局样式表。所有颜色/字号都取自本模块常量，便于统一调整。"""
    fam = cn_font_family()
    return f"""
    QWidget {{
        background-color: {BG};
        color: {TEXT_SOFT};
        font-family: "{fam}";
        font-size: {FS_CAPTION}pt;
    }}
    QMainWindow, QDialog {{ background-color: {BG}; }}
    QLabel {{ background: transparent; color: {TEXT_SOFT}; }}

    QPushButton {{
        background-color: {SURFACE_SOFT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 7px 14px;
        font-size: {FS_CAPTION}pt;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {shade(SURFACE_SOFT, 1.25)};
        border-color: {BORDER_FOCUS};
    }}
    QPushButton:pressed {{ background-color: {shade(SURFACE_SOFT, 0.85)}; }}
    QPushButton:disabled {{
        background-color: {BG_ELEVATED};
        color: {TEXT_FAINT};
        border-color: {SURFACE_ALT};
    }}

    /* 主操作按钮：加 setProperty("accent", True) 即生效 */
    QPushButton[accent="true"] {{
        background-color: {PRIMARY};
        border: none;
        color: #FFFFFF;
    }}
    QPushButton[accent="true"]:hover {{ background-color: {PRIMARY_HOVER}; }}
    QPushButton[accent="true"]:pressed {{ background-color: {shade(PRIMARY, 0.88)}; }}
    QPushButton[accent="true"]:disabled {{
        background-color: {SURFACE_ALT};
        color: {TEXT_FAINT};
    }}
    /* 危险操作（停止推流 / 退出登录） */
    QPushButton[danger="true"] {{
        background-color: {RED};
        border: none;
        color: #FFFFFF;
    }}
    QPushButton[danger="true"]:hover {{ background-color: {shade(RED, 1.1)}; }}
    QPushButton[danger="true"]:pressed {{ background-color: {RED_DARK}; }}
    /* 次要文本按钮（返回等） */
    QPushButton[ghost="true"] {{
        background: transparent;
        border: 1px solid {BORDER};
        color: {TEXT_MUTED};
        font-weight: normal;
    }}
    QPushButton[ghost="true"]:hover {{
        color: {TEXT};
        border-color: {BORDER_FOCUS};
    }}

    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {SURFACE_SOFT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 7px 10px;
        font-size: {FS_BODY}pt;
        selection-background-color: {PRIMARY};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QLineEdit:disabled, QTextEdit:disabled {{
        background-color: {BG_ELEVATED};
        color: {TEXT_FAINT};
    }}

    QComboBox {{
        background-color: {SURFACE_SOFT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: {FS_CAPTION}pt;
    }}
    QComboBox:hover {{ border-color: {BORDER_FOCUS}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background-color: {SURFACE_ALT};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {PRIMARY};
        selection-color: #FFFFFF;
        outline: none;
    }}

    QCheckBox {{
        color: {TEXT_SOFT};
        font-size: {FS_SMALL}pt;
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {BORDER};
        border-radius: 4px;
        background-color: {SURFACE_SOFT};
    }}
    QCheckBox::indicator:hover {{ border-color: {BORDER_FOCUS}; }}
    QCheckBox::indicator:checked {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}

    QSlider::groove:horizontal {{
        background: {SURFACE_ALT};
        height: 6px;
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {PRIMARY};
        height: 6px;
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: #FFFFFF;
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}

    QFrame[card="true"] {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER}; border-radius: 4px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QToolTip {{
        background-color: {SURFACE_ALT};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 4px;
    }}
    """


# ====================== 常用内联样式片段 ======================
def label_style(size=FS_CAPTION, color=TEXT_SOFT, bold=False):
    """给单个 QLabel 用的内联样式，避免各处手写颜色。"""
    weight = "bold" if bold else "normal"
    return f"color:{color};font-size:{size}pt;font-weight:{weight};background:transparent;"


def section_title_style():
    return label_style(FS_H2, TEXT, bold=True)


def caption_style():
    return label_style(FS_SMALL, TEXT_MUTED)


def set_button_role(button, role="default"):
    """切换按钮语义角色并立即刷新动态属性样式。"""
    button.setProperty("accent", role == "primary")
    button.setProperty("danger", role == "danger")
    button.setProperty("ghost", role == "ghost")
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()
