# -*- coding: utf-8 -*-
"""
电荷 + 键级 组合面板（主窗口右侧 QTabWidget 的一个页签）。

将 charge_viewer.ChargePanel 与 BondOrderPanel 纵向组合到同一个面板内，
分上下两组（以分组框区分），共用左侧 OpenGL 画布（glw）。
这样既保留两个面板的全部功能，又减少主窗口 tab 数量。

设计：
  - 本面板作为「容器」，内部持有 self.charge / self.bond 两个子面板；
  - 对外接口 set_lang / shutdown / reset_view_state 转发给两个子面板；
  - 两个子面板都向 glw 注册了 atom pick 回调，画布点击会同时触发
    （电荷高亮 + 键级选中），符合「点原子既看电荷又选键级」的预期。
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox


class ChargeBondPanel(QWidget):
    """电荷分析与 Mayer 键级分析的合并面板。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None,
                 get_multiwfn=None, log_func=None, parent=None):
        super().__init__(parent)

        # 延迟导入，避免主窗口模块顶层导入循环
        from charge_viewer import ChargePanel, BondOrderPanel

        self.charge = ChargePanel(
            glw=glw,
            multiwfn_path=multiwfn_path,
            get_fchk=get_fchk,
            get_multiwfn=get_multiwfn,
            log_func=log_func,
            parent=self,
        )
        self.bond = BondOrderPanel(
            glw=glw,
            multiwfn_path=multiwfn_path,
            get_fchk=get_fchk,
            get_multiwfn=get_multiwfn,
            log_func=log_func,
            parent=self,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        g_charge = QGroupBox(self._tr("grp_charge"))
        cv = QVBoxLayout(g_charge)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.charge)
        root.addWidget(g_charge, stretch=1)
        self.g_charge = g_charge

        g_bond = QGroupBox(self._tr("grp_bond"))
        bv = QVBoxLayout(g_bond)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.addWidget(self.bond)
        root.addWidget(g_bond, stretch=1)
        self.g_bond = g_bond

    # ── i18n ──
    def _tr(self, key, **fmt):
        import i18n
        return i18n.tr(key, **fmt)

    def set_lang(self, lang):
        self.charge.set_lang(lang)
        self.bond.set_lang(lang)
        # 用保存的引用更新两个分组框标题（findChildren 顺序不可靠）
        if getattr(self, "g_charge", None) is not None:
            self.g_charge.setTitle(self._tr("grp_charge"))
        if getattr(self, "g_bond", None) is not None:
            self.g_bond.setTitle(self._tr("grp_bond"))

    def reset_view_state(self):
        """新分子载入时清空电荷着色与键级选中（由主窗口调用）。"""
        if hasattr(self.charge, "reset_charge_view"):
            self.charge.reset_charge_view()
        if hasattr(self.bond, "reset_view_state"):
            self.bond.reset_view_state()

    def shutdown(self):
        if hasattr(self.charge, "shutdown"):
            try:
                self.charge.shutdown()
            except Exception:
                pass
        if hasattr(self.bond, "shutdown"):
            try:
                self.bond.shutdown()
            except Exception:
                pass
