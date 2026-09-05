# -*- coding: utf-8 -*-
"""试用版（Trial）本地有效期检查。

设计要点：
- 纯本地时间判断，**不连接任何后端服务器**；
- 总开关在 core.config.TRIAL_ENABLED：正式版发布时改为 False（或删掉
  main.py 中的调用点）即可完全关闭检查，其余业务逻辑零改动；
- 截止日 core.config.TRIAL_EXPIRE_DATE 当天（含）全天可用，次日 0 点起
  禁止进入登录；动态读取 config 属性，改配置即时生效、也便于测试替换。

已知边界（按需求保持简单，刻意不做）：本检查只看系统本地时间，用户回拨
系统时钟可绕过。如需防回拨（记录历史最大时间戳）再另行加固。
"""
from datetime import datetime, timedelta

from core import config


def _expire_text():
    y, m, d = config.TRIAL_EXPIRE_DATE
    return "%04d-%02d-%02d" % (y, m, d)


def _deadline():
    """禁止时刻 = 截止日次日 0 点（即截止日当天 23:59:59.999 仍可用）。"""
    return datetime(*config.TRIAL_EXPIRE_DATE) + timedelta(days=1)


def trial_active(now=None):
    """当前是否处于「已启用的试用期内」：开关开 且 未过截止时刻。

    UI 层用本函数决定是否走本地试用登录（不连接任何服务器）。
    """
    return bool(config.TRIAL_ENABLED) and trial_blocked(now) is None


def trial_blocked(now=None):
    """检查试用期是否已过。

    返回 None 表示可用（含「开关关闭 = 不启用 Trial」的情形）；
    返回非 None 字符串则为禁止原因文案，调用方据此弹窗并退出。
    now 参数仅供测试注入时间，正常调用留空取当前本地时间。
    """
    if not config.TRIAL_ENABLED:
        return None
    moment = now if now is not None else datetime.now()
    if moment >= _deadline():
        return (
            "试用版已到期。\n\n"
            "有效期至 %s（含当日），现已超出试用期，软件已停止使用。\n"
            "请联系供应商获取正式版本。" % _expire_text()
        )
    return None


def trial_remaining_days(now=None):
    """距到期还剩几天（向上取整天数，当天返回 1）。开关关闭时返回 None。"""
    if not config.TRIAL_ENABLED:
        return None
    moment = now if now is not None else datetime.now()
    delta = _deadline() - moment
    if delta.total_seconds() <= 0:
        return 0
    return max(1, delta.days + (1 if delta.seconds or delta.microseconds else 0))
