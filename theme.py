"""
theme: QSS 主题样式表
提供 LIGHT_QSS 浅色科技风主题。
"""

LIGHT_QSS = """
/* ── Global ── */
QMainWindow {
    background-color: #E4EAF2;
}

QWidget {
    font-family: "Microsoft YaHei", "Segoe UI", "Consolas", sans-serif;
    font-size: 9.5pt;
    color: #2C3E50;
}

/* ── Group Box ── */
QGroupBox {
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    margin-top: 16px;
    padding: 18px 12px 12px 12px;
    background-color: #FFFFFF;
    font-weight: bold;
    font-size: 10pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 2px 12px 2px 12px;
    color: #FFFFFF;
    background-color: #1565C0;
    border-radius: 4px;
    font-size: 9pt;
}

/* ── VMD 控制台卡片：与画布下方「一键样式」区同款浅色渐变 ── */
QGroupBox#VmdConsoleBox {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #FFFFFF, stop:1 #F1F5FB);
    border: 1px solid #D5DEE9;
    border-radius: 12px;
}

/* ── VMD 控制台内嵌卡片：标题条画进边框内部，避免溢出与上方卡片重叠 ── */
QGroupBox#AimVmdBox {
    margin-top: 0px;
    padding: 32px 12px 10px 12px;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    background-color: #FFFFFF;
}

QGroupBox#AimVmdBox::title {
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 16px;
    top: 6px;
    padding: 2px 12px 2px 12px;
    color: #FFFFFF;
    background-color: #1565C0;
    border-radius: 4px;
    font-size: 9pt;
}

/* ── Labels ── */
QLabel {
    color: #4A5568;
    padding: 1px 0px;
}

QLabel#TitleLabel {
    color: #0D47A1;
    font-size: 16pt;
    font-weight: bold;
    padding: 6px 8px 2px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#SubTitleLabel {
    color: #5C6BC0;
    font-size: 8.5pt;
    padding: 0px 8px 8px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#ProgressLabel {
    color: #1565C0;
    font-size: 9pt;
    font-weight: bold;
    padding: 5px 12px;
    background-color: #EEF2FF;
    border: 1px solid #C5CAE9;
    border-radius: 4px;
}

QLabel#HintLabel {
    color: #7986CB;
    font-size: 8pt;
    padding: 1px 4px;
}

/* ── Line Edit ── */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #2C3E50;
    selection-background-color: #1E88E5;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 1px solid #1E88E5;
    background-color: #F8FAFE;
}

QLineEdit:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border: 1px solid #E2E8F0;
}

/* ── Combo Box ── */
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #2C3E50;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #1E88E5;
}

QComboBox:hover {
    border: 1px solid #5C6BC0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #E2E8F0;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    background-color: #F8FAFE;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    selection-background-color: #E3F2FD;
    selection-color: #1565C0;
    outline: none;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #E8EAF6;
    color: #1A237E;
}

/* ── Radio Button ── */
QRadioButton {
    color: #4A5568;
    spacing: 6px;
    padding: 3px 6px;
}

QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border-radius: 8px;
    border: 2px solid #A0AEC0;
    background-color: #FFFFFF;
}

QRadioButton::indicator:checked {
    border: 2px solid #1E88E5;
    background-color: #1E88E5;
}

QRadioButton::indicator:hover {
    border: 2px solid #5C6BC0;
}

QRadioButton:checked {
    color: #1565C0;
    font-weight: bold;
}

/* ── Check Box ── */
QCheckBox {
    color: #4A5568;
    spacing: 6px;
    padding: 3px 6px;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 2px solid #A0AEC0;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    border: 2px solid #1E88E5;
    background-color: #1E88E5;
}

QCheckBox::indicator:hover {
    border: 2px solid #5C6BC0;
}

QCheckBox:checked {
    color: #1565C0;
}

/* ── Push Button ── */
QPushButton {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 6px 16px;
    color: #2C3E50;
    font-weight: bold;
    font-size: 9pt;
}

QPushButton:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton:pressed {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QPushButton#PrimaryBtn {
    background-color: #1565C0;
    border: 1px solid #0D47A1;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#PrimaryBtn:hover {
    background-color: #1E88E5;
    border: 1px solid #1565C0;
    color: #FFFFFF;
}

QPushButton#PrimaryBtn:pressed {
    background-color: #0D47A1;
}

QPushButton#RenderBtn {
    background-color: #00897B;
    border: 1px solid #00695C;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#RenderBtn:hover {
    background-color: #26A69A;
    border: 1px solid #00897B;
    color: #FFFFFF;
}

QPushButton#RenderBtn:pressed {
    background-color: #00695C;
}

QPushButton#StopBtn {
    background-color: #FFFFFF;
    border: 1px solid #E53935;
    color: #E53935;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#StopBtn:hover {
    background-color: #FFEBEE;
    border: 1px solid #EF5350;
    color: #D32F2F;
}

QPushButton#StopBtn:pressed {
    background-color: #FFCDD2;
}

QPushButton#ActionBtn {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    font-weight: bold;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#ActionBtn:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton#ActionBtn:pressed {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
}

QPushButton#ActionBtn:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QPushButton#ActionBtnSmall {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    font-weight: bold;
    font-size: 9pt;
    padding: 6px 10px;
}

QPushButton#ActionBtnSmall:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton#ActionBtnSmall:pressed {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
}

QPushButton#ActionBtnSmall:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QPushButton#SmallBtn {
    padding: 5px 12px;
    font-size: 9pt;
    min-width: 34px;
}

QPushButton#SmallBtn:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton#GhostBtn {
    background-color: transparent;
    border: none;
    color: #1565C0;
    font-weight: bold;
    padding: 4px 12px;
}

QPushButton#GhostBtn:hover {
    background-color: #E3F2FD;
}

/* ── Text Edit (Log) ── */
QTextEdit {
    background-color: #F5F6FA;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 10px;
    color: #1E293B;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.5pt;
    selection-background-color: #BBDEFB;
    selection-color: #0D47A1;
}

QTextEdit:focus {
    border: 1px solid #1E88E5;
}

QScrollBar:vertical {
    background-color: #F1F5F9;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #CBD5E1;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #1E88E5;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}

QScrollBar:horizontal {
    background-color: #F1F5F9;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #CBD5E1;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #1E88E5;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}

/* ── Frame separator ── */
QFrame#Separator {
    background-color: #CBD5E1;
    max-height: 1px;
}

/* ── Scroll Area ── */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* ── Viewer Frame ── */
QFrame#ViewerFrame {
    background-color: #FFFFFF;
    border: 2px solid #CBD5E1;
    border-radius: 8px;
    padding: 3px;
}

/* ── Slider ── */
QSlider::groove:horizontal {
    border: 1px solid #CBD5E1;
    height: 8px;
    background-color: #F1F5F9;
    border-radius: 4px;
}

QSlider::sub-page:horizontal {
    background-color: #1E88E5;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background-color: #FFFFFF;
    border: 2px solid #1E88E5;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background-color: #E3F2FD;
    border: 2px solid #1565C0;
}

QSlider::handle:horizontal:pressed {
    background-color: #BBDEFB;
    border: 2px solid #0D47A1;
}

QSlider:disabled {
    color: #94A3B8;
}

QSlider::groove:horizontal:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
}

QSlider::handle:horizontal:disabled {
    background-color: #F1F5F9;
    border: 2px solid #E2E8F0;
}

/* ── Tooltip ── */
QToolTip {
    border: none;
    padding: 4px 8px;
    color: #2C3E50;
    font-size: 8.5pt;
}

/* ── Tab Widget ── */
QTabWidget::pane {
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    background-color: #FFFFFF;
    padding: 8px;
}

/* 主窗口白色圆角卡片：左侧功能导航条 + 右侧参数设置区 */
QFrame#NavCard, QFrame#RightCard {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 10px;
}

QListWidget#MainNav {
    background: transparent;
    border: none;
    color: #4A5568;
    font-weight: bold;
    font-size: 9.5pt;
    outline: none;
}

QListWidget#MainNav::item {
    padding: 12px 10px;
    border-bottom: 1px solid #EEF2F7;
}

QListWidget#MainNav::item:selected {
    background-color: #E3F2FD;
    color: #1565C0;
    border-left: 3px solid #1E88E5;
}

QListWidget#MainNav::item:hover:!selected {
    background-color: #E8EFF7;
    color: #1565C0;
}

QTabBar::tab {
    background-color: #F1F5F9;
    border: 1px solid #CBD5E1;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 28px;
    margin-right: 3px;
    min-width: 80px;
    color: #4A5568;
    font-weight: bold;
    font-size: 9pt;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1565C0;
    border-bottom: 2px solid #1E88E5;
}

QTabBar::tab:hover:!selected {
    background-color: #E3F2FD;
    color: #1565C0;
}

QTabBar::tab:disabled {
    color: #94A3B8;
    background-color: #F1F5F9;
}

/* ── Splitter 分隔条 ──
   左右栏宽度靠拖动这条分隔条调整。默认画成浅灰「小药丸」，
   悬停/拖拽时变主题蓝，让用户一眼看出这里能拖（默认样式又细又透明，
   看不出来可拖）。热区宽度也由 main_window 的 setHandleWidth(8) 保证。 */
QSplitter::handle {
    background-color: transparent;
}

QSplitter::handle:horizontal {
    width: 8px;
    margin: 6px 2px;
    border-radius: 4px;
    background-color: #DCE3EC;
}

QSplitter::handle:horizontal:hover,
QSplitter::handle:horizontal:pressed {
    background-color: #1E88E5;
}

QSplitter::handle:vertical {
    height: 8px;
    margin: 2px 6px;
    border-radius: 4px;
    background-color: #DCE3EC;
}

QSplitter::handle:vertical:hover,
QSplitter::handle:vertical:pressed {
    background-color: #1E88E5;
}
"""
