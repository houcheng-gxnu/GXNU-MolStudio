# -*- coding: utf-8 -*-
"""独立启动 ORCA 本机计算弹窗：``python -m molstudio.orca_gui [结构文件]``。"""

from __future__ import annotations

import argparse
import sys

from PyQt5.QtWidgets import QApplication

from molstudio.panels.orca_local_dialog import OrcaLocalDialog


def main(argv=None):
    parser = argparse.ArgumentParser(description="MolStudio ORCA local calculator")
    parser.add_argument("structure", nargs="?", default="",
                        help="xyz / gjf / fchk / log / out")
    parser.add_argument("--orca", default="", help="orca.exe 路径")
    args, _unknown = parser.parse_known_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        from molstudio.ui.theme import LIGHT_QSS
        app.setStyleSheet(LIGHT_QSS)
    except Exception:                                    # noqa: BLE001
        pass
    dlg = OrcaLocalDialog(initial_path=args.structure, orca_exe=args.orca)
    dlg.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
