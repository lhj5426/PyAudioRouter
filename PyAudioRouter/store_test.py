"""验证规则按 exe 路径隔离：同一游戏复制多份（同名 exe、不同目录）互不影响。"""
import tempfile
from pathlib import Path

from store import Store


def main():
    tmp = Path(tempfile.mkdtemp()) / "rules.json"
    st = Store(tmp)

    st.set("game", "DEV_A", 0, r"C:\games\slot1\game.exe")
    st.set("game", "DEV_B", 0, r"C:\games\slot2\game.exe")
    st.set("game", "DEV_C", 0, r"D:\另一份\game.exe")
    print("规则数:", st.count(), "(应为 3)")

    cases = [
        (r"c:\GAMES\slot1\GAME.EXE", "DEV_A", "大小写不敏感"),
        (r"C:/games/slot2/game.exe", "DEV_B", "正斜杠归一化"),
        (r"D:\另一份\game.exe", "DEV_C", "中文路径"),
        (r"C:\games\slot3\game.exe", "", "未设置的副本应为空"),
    ]
    ok = True
    for path, want, note in cases:
        got = st.get("game", 0, path)
        flag = "OK" if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{flag}] {note}: {path} -> {got!r}")

    # 只清掉其中一个副本，其他不受影响
    st.set("game", "", 0, r"C:\games\slot1\game.exe")
    a = st.get("game", 0, r"C:\games\slot1\game.exe")
    b = st.get("game", 0, r"C:\games\slot2\game.exe")
    print(f"  清除 slot1 后: slot1={a!r} slot2={b!r} 剩余规则={st.count()}")
    if a != "" or b != "DEV_B" or st.count() != 2:
        ok = False

    # 旧版按进程名存的规则仍能被读到（向后兼容）
    tmp2 = Path(tempfile.mkdtemp()) / "rules.json"
    st2 = Store(tmp2)
    st2.set("oldgame", "DEV_X", 0)
    got = st2.get("oldgame", 0, r"C:\x\oldgame.exe")
    print(f"  兼容旧键: {got!r} (应为 DEV_X)")
    if got != "DEV_X":
        ok = False

    print("全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
