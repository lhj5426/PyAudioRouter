"""离屏构造测试：不显示窗口，验证 UI 构建、刷新、主题切换不抛异常。"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import main as m


def run():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = m.MainWindow()
    win.show()
    print("窗口构建成功", win.size())
    print("设备数:", len(win.devices))
    print("会话行:", len(win.rows))
    for row in win.rows.values():
        print("  -", row.session.title, "| 下拉:", row.combo.currentText(),
              "| 音量:", row.slider.value())

    def step2():
        win.toggle_theme()
        print("深色主题切换 OK")
        win.refresh(full=True)
        print("刷新 OK，会话行:", len(win.rows))

    def step3():
        win.toggle_theme()
        win.refresh(full=True)
        print("二次刷新 OK，会话行:", len(win.rows))
        win._update_status()
        print("状态栏:", win.status_label.text())
        for row in list(win.rows.values())[:3]:
            print("  ", row.session.title, "| 路径:", row._full_path[:60],
                  "| 下拉:", row.combo.currentText())
        app.quit()

    QTimer.singleShot(600, step2)
    QTimer.singleShot(1200, step3)
    app.exec()
    print("全部通过")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
