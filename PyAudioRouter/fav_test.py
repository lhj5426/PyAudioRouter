"""离屏测试收藏功能：收藏 → 筛选 → 取消 → 清空。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYAUDIOROUTER_DATA",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))

from PySide6.QtWidgets import QApplication

import main as m


def run():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = m.MainWindow()
    win.refresh(full=True)
    rows = list(win.rows.values())
    print("初始会话:", len(rows), "收藏数:", win.store.fav_count())

    if not rows:
        print("没有音频会话，无法测试")
        return 1

    target = rows[0]
    name = target.session.title
    win._on_fav_toggled(target.session)
    print(f"收藏 {name} -> 收藏数 {win.store.fav_count()}, 星标 {target.fav_btn.text()}")

    win._on_filter_changed(1)
    print("切到收藏标签，行数:", len(win.rows))
    ok1 = len(win.rows) == 1 and list(win.rows.values())[0].session.title == name

    # 再收藏一个（如果还有别的会话）
    win._on_filter_changed(0)
    if len(win.rows) > 1:
        second = [r for r in win.rows.values() if r.session.title != name][0]
        win._on_fav_toggled(second.session)
        print("再收藏", second.session.title, "-> 收藏数", win.store.fav_count())
        win._on_filter_changed(1)
        print("收藏标签行数:", len(win.rows))

    # 取消收藏，应从收藏列表消失
    win._on_filter_changed(1)
    first = list(win.rows.values())[0]
    win._on_fav_toggled(first.session)
    print("取消收藏后收藏标签行数:", len(win.rows), "收藏数:", win.store.fav_count())

    # 全部取消
    win._on_filter_changed(0)
    for r in list(win.rows.values()):
        if r._fav:
            win._on_fav_toggled(r.session)
    print("最终收藏数:", win.store.fav_count())
    print("收藏筛选生效:", "通过" if ok1 else "失败")
    win._quit()
    return 0 if ok1 else 1


if __name__ == "__main__":
    sys.exit(run())
