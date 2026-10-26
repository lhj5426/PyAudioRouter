"""多声卡窗口管理 —— 启动入口。

    python run.py

当前解释器缺依赖时，会自动换一个装好依赖的解释器重新拉起自己
（路径记进 runtime.txt，下次直接用）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "runtime.txt")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- #
# 解释器探测（只用标准库）
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=25,
                          creationflags=NO_WINDOW)


def _candidates() -> list[str]:
    """按优先级列出可能的 python.exe：记住的 > py 启动器 > PATH > 常见位置。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(p: str | None):
        if not p:
            return
        p = os.path.normpath(p.strip().strip('"'))
        if not p.lower().endswith(".exe"):
            return
        k = p.lower()
        if k in seen or not os.path.isfile(p):
            return
        seen.add(k)
        out.append(p)

    try:
        with open(RUNTIME, encoding="utf-8") as f:
            add(f.read())
    except Exception:
        pass
    try:
        r = _run(["py", "-3", "-c", "import sys;print(sys.executable)"])
        if r.returncode == 0:
            add(r.stdout.strip())
    except Exception:
        pass
    try:
        r = _run(["where", "python.exe"])
        for line in (r.stdout or "").splitlines():
            add(line)
    except Exception:
        pass

    local = os.environ.get("LOCALAPPDATA", "")
    for ver in ("313", "312", "311", "310"):
        add(os.path.join(local, "Programs", "Python", f"Python{ver}", "python.exe"))
        add(fr"C:\Python{ver}\python.exe")
    add(r"C:\ProgramData\miniconda3\python.exe")
    add(r"C:\ProgramData\Anaconda3\python.exe")
    return out


def _has(py: str, module: str) -> bool:
    if not py or not os.path.isfile(py):
        return False
    try:
        return _run([py, "-c", f"import {module}"]).returncode == 0
    except Exception:
        return False


def _find_python() -> str | None:
    for py in _candidates():
        if _has(py, "PySide6") and _has(py, "comtypes"):
            return py
    for py in _candidates():
        if _has(py, "PySide6"):
            return py
    return None


def _pythonw(py: str) -> str:
    d = os.path.dirname(py)
    w = os.path.join(d, "pythonw.exe")
    return w if os.path.isfile(w) else py


def _save_runtime(py: str) -> None:
    try:
        with open(RUNTIME, "w", encoding="utf-8") as f:
            f.write(py)
    except Exception:
        pass


def _error(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "多声卡窗口管理", 0x10)
    except Exception:
        print(text)


def _hide_console() -> None:
    """用 python.exe 启动时藏掉黑色控制台窗口。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        import PySide6  # noqa: F401
        import comtypes  # noqa: F401
    except ImportError:
        py = _find_python()
        if py and os.path.normcase(py) != os.path.normcase(sys.executable):
            _save_runtime(py)
            try:
                subprocess.Popen([_pythonw(py), os.path.abspath(__file__)],
                                 creationflags=NO_WINDOW)
                return 0
            except Exception as exc:
                _error(f"启动失败：{exc}")
                return 1
        _error("缺少运行库 PySide6 / comtypes。\n\n"
               "请在本目录执行：\n\n    pip install -r requirements.txt")
        return 1

    _hide_console()
    try:
        import main
        main.main()
    except SystemExit:
        raise
    except Exception:
        _error("程序异常：\n\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
