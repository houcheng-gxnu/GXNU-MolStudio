# -*- coding: utf-8 -*-
"""ORCA 本机运行后台线程（弹窗与 ORCA 页共用）。"""

from __future__ import annotations

import os

from PyQt5.QtCore import QThread, pyqtSignal

from molstudio.core import orca_run as ORCA


class OrcaWorker(QThread):
    """生成输入 + 运行 ORCA + 自动转 Molden / fchk。"""
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
        try:
            prepared = ORCA.prepare_job(
                cfg["workdir"], cfg["name"], cfg["symbols"], cfg["coords"],
                charge=cfg["charge"], mult=cfg["mult"], method=cfg["method"],
                basis=cfg["basis"], task=cfg["task"], nprocs=cfg["nprocs"],
                maxcore=cfg["maxcore"], solvent=cfg["solvent"],
                solvent_model=cfg["solvent_model"],
                dispersion=cfg["dispersion"],
                extra_keywords=cfg["extra"], td_nroots=cfg["nroots"],
                orca_exe=cfg["orca_exe"])
            self.stage.emit("输入：%s" % prepared.inp_path)
            self.log_line.emit("[MolStudio] 命令：%s" % prepared.command_str)
            result = ORCA.run_job(
                prepared, orca_exe=cfg["orca_exe"],
                on_log=self.log_line.emit,
                cancel_check=lambda: self._cancel,
                timeout=cfg.get("timeout", 0))
            if self._cancel:
                self.failed.emit("__cancelled__")
                return
            molden = ""
            if result.gbw_path and os.path.isfile(result.gbw_path):
                try:
                    self.stage.emit("Molden 转换中…")
                    molden = ORCA.convert_gbw(result.gbw_path, cfg["orca_exe"])
                    result.parsed["molden_path"] = molden
                    self.log_line.emit("[MolStudio] Molden：%s" % molden)
                except Exception as exc:                 # noqa: BLE001
                    self.log_line.emit("[MolStudio] Molden 转换失败：%s" % exc)
            if molden:
                try:
                    self.stage.emit("fchk 转换中（Multiwfn）…")
                    fchk = ORCA.molden_to_fchk(
                        molden, cfg.get("multiwfn_exe", ""))
                    result.parsed["fchk_path"] = fchk
                    self.log_line.emit("[MolStudio] FCHK：%s" % fchk)
                except Exception as exc:                 # noqa: BLE001
                    self.log_line.emit("[MolStudio] FCHK 转换失败：%s" % exc)
            if result.error and not result.parsed.get("terminated_normally"):
                self.failed.emit(result.error)
            else:
                self.finished_ok.emit(result)
        except Exception as exc:                         # noqa: BLE001
            self.failed.emit(str(exc))
