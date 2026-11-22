# -*- coding: utf-8 -*-
"""高斯计算页的后台线程（跑 g16 → 跟随 .log 输出 → 解析 → chk 转 fchk）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PyQt5.QtCore import QThread, pyqtSignal

from molstudio.core import gaussian_run as G


@dataclass
class GaussianTabResult:
    """一次高斯计算在界面层需要的东西。"""

    workdir: str
    gjf_path: str
    log_path: str
    chk_path: str = ""
    fchk_path: str = ""
    parsed: dict = field(default_factory=dict)
    elapsed: float = 0.0
    returncode: int = -1
    normal: bool = False
    bridge: bool = False
    error: str = ""


class GaussianWorker(QThread):
    """生成输入 → 跑 Gaussian → 解析日志 → 转 fchk。"""

    log_line = pyqtSignal(str)
    stage = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        cfg = self.config
        gjf = str(cfg.get("gjf_path") or "")
        log = str(cfg.get("log_path") or "")

        def on_line(line):
            self.log_line.emit(str(line).rstrip("\r\n"))

        try:
            self.stage.emit("Gaussian 运行中…")
            outcome = G.run_gaussian(
                gjf, g16_exe=cfg.get("g16_exe", ""), log_path=log,
                on_line=on_line, cancel=lambda: self._cancel,
                timeout=cfg.get("timeout", 0) or None,
                extra_env=cfg.get("extra_env") or None)
        except Exception as exc:                            # noqa: BLE001
            self.failed.emit(str(exc))
            return

        if self._cancel and not outcome.ok:
            self.failed.emit("__cancelled__")
            return

        text = ""
        parsed = {}
        try:
            if os.path.isfile(log):
                text = open(log, "r", encoding="utf-8",
                            errors="replace").read()
            parsed = G.parse_output(text)
        except OSError:
            parsed = {}

        chk = ""
        fchk = ""
        if outcome.ok:
            try:
                chk = G.find_chk_file(log) or ""
            except Exception:                               # noqa: BLE001
                chk = ""
            if chk:
                try:
                    self.stage.emit("转换为 .fchk…")
                    fchk = G.chk_to_fchk(chk, cfg.get("formchk_exe", ""))
                    self.log_line.emit("[MolStudio] FCHK：%s" % fchk)
                except Exception as exc:                    # noqa: BLE001
                    self.log_line.emit("[MolStudio] fchk 转换失败：%s" % exc)

        result = GaussianTabResult(
            workdir=os.path.dirname(log) or "",
            gjf_path=gjf, log_path=log, chk_path=chk, fchk_path=fchk,
            parsed=parsed, elapsed=outcome.seconds,
            returncode=int(outcome.returncode), normal=bool(outcome.ok),
            bridge=bool(parsed.get("bridge")),
            error="" if outcome.ok else (outcome.error or "Gaussian 未正常结束"))

        if outcome.ok or self._cancel:
            self.finished_ok.emit(result)
        else:
            self.failed.emit(result.error or "Gaussian 未正常结束")
