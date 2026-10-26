"""store.py — 规则持久化（JSON）"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


APP_NAME = "PyAudioRouter"


def data_dir() -> Path:
    """配置目录：优先 %APPDATA%，不可写则退到程序目录下的 data\\。"""
    override = os.environ.get("PYAUDIOROUTER_DATA")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    for env in ("APPDATA", "LOCALAPPDATA"):
        v = os.environ.get(env)
        if v:
            candidates.append(Path(v) / APP_NAME)
    candidates.append(Path(__file__).resolve().parent / "data")
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_test"
            probe.write_text("1", encoding="utf-8")
            probe.unlink()
            return d
        except Exception:
            continue
    return Path(__file__).resolve().parent


class Store:
    """规则表：exe 完整路径 -> 设备 ID。

    用完整路径而不是进程名做键——同一个游戏复制多份放在不同目录时，
    进程名（如 game.exe）完全相同，只有路径能区分。读不到路径时才退化为进程名。
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "rules.json")
        self._lock = threading.RLock()
        self._rules: dict[str, dict] = {}
        self._favorites: set[str] = set()
        self.settings: dict = {
            "theme": "light",
            "auto_apply": True,
            "minimize_to_tray": True,
            "show_system_sounds": False,
            "win": [],
            "hidden": {},          # 已移除的应用：key -> {name, path}
        }
        self.load()

    # -- 基础 ---------------------------------------------------------------
    @staticmethod
    def key(process_name: str, exe_path: str = "") -> str:
        p = (exe_path or "").strip().replace("/", "\\").lower()
        if p:
            return p
        k = (process_name or "").strip().lower()
        if k.endswith(".exe"):
            k = k[:-4]
        return k

    @staticmethod
    def _legacy_key(process_name: str) -> str:
        k = (process_name or "").strip().lower()
        if k.endswith(".exe"):
            k = k[:-4]
        return k

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        with self._lock:
            rules = raw.get("rules") or {}
            if isinstance(rules, dict):
                self._rules = {str(k).lower(): v for k, v in rules.items() if isinstance(v, dict)}
            favs = raw.get("favorites") or []
            if isinstance(favs, list):
                self._favorites = {str(x).lower() for x in favs if isinstance(x, str) and x}
            st = raw.get("settings") or {}
            if isinstance(st, dict):
                self.settings.update({k: v for k, v in st.items() if k in self.settings})

    def save(self):
        with self._lock:
            payload = {
                "version": 1,
                "rules": self._rules,
                "favorites": sorted(self._favorites),
                "settings": self.settings,
            }
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, self.path)
            except Exception:
                pass

    # -- 收藏 ---------------------------------------------------------------
    def is_fav(self, process_name: str, exe_path: str = "") -> bool:
        k = self.key(process_name, exe_path)
        with self._lock:
            return bool(k) and k in self._favorites

    def remove_fav(self, key: str):
        """按存储键直接取消收藏（收藏页管理用）。"""
        with self._lock:
            gone = str(key).lower() in self._favorites
            self._favorites.discard(str(key).lower())
        if gone:
            self.save()

    def toggle_fav(self, process_name: str, exe_path: str = "") -> bool:
        """切换收藏，返回切换后是否已收藏。"""
        k = self.key(process_name, exe_path)
        if not k:
            return False
        with self._lock:
            if k in self._favorites:
                self._favorites.discard(k)
                on = False
            else:
                self._favorites.add(k)
                on = True
        self.save()
        return on

    def get_device_name(self, process_name: str, flow: int = 0, exe_path: str = "") -> str:
        """规则里记住的设备名（设备 ID 失效时用来按名字找回）。"""
        with self._lock:
            r = self._rules.get(self.key(process_name, exe_path))
            if not r or int(r.get("flow", 0)) != int(flow):
                return ""
            return r.get("device_name") or ""

    def favorites(self) -> set[str]:
        with self._lock:
            return set(self._favorites)

    def fav_count(self) -> int:
        with self._lock:
            return len(self._favorites)

    # -- 规则 ---------------------------------------------------------------
    def get(self, process_name: str, flow: int = 0, exe_path: str = "") -> str:
        with self._lock:
            r = self._rules.get(self.key(process_name, exe_path))
            if not r and exe_path:
                # 兼容旧版按进程名存的规则
                r = self._rules.get(self._legacy_key(process_name))
            if not r:
                return ""
            if int(r.get("flow", 0)) != int(flow):
                return ""
            return r.get("device") or ""

    def set(self, process_name: str, device_id: str, flow: int = 0,
            exe_path: str = "", device_name: str = ""):
        k = self.key(process_name, exe_path)
        if not k:
            return
        with self._lock:
            if device_id:
                self._rules[k] = {"device": device_id, "flow": int(flow),
                                  "name": process_name, "path": exe_path,
                                  "device_name": device_name}
            else:
                self._rules.pop(k, None)
        self.save()

    def remove(self, process_name: str, exe_path: str = ""):
        with self._lock:
            self._rules.pop(self.key(process_name, exe_path), None)
            # 旧版按进程名存的规则也要一起删，否则 get() 还能从那里读回来
            legacy = self._legacy_key(process_name)
            if legacy:
                self._rules.pop(legacy, None)
        self.save()

    def clear(self, flow: int | None = None):
        with self._lock:
            if flow is None:
                self._rules.clear()
            else:
                for k in [k for k, v in self._rules.items() if int(v.get("flow", 0)) == int(flow)]:
                    self._rules.pop(k, None)
        self.save()

    # -- 已移除的应用 -------------------------------------------------------
    def hidden_items(self) -> dict[str, dict]:
        with self._lock:
            return dict(self.settings.get("hidden") or {})

    def is_hidden(self, process_name: str, exe_path: str = "") -> bool:
        k = self.key(process_name, exe_path)
        with self._lock:
            return bool(k) and k in (self.settings.get("hidden") or {})

    def hide(self, process_name: str, exe_path: str = ""):
        k = self.key(process_name, exe_path)
        if not k:
            return
        with self._lock:
            h = dict(self.settings.get("hidden") or {})
            h[k] = {"name": process_name or k, "path": exe_path or ""}
            self.settings["hidden"] = h
        self.save()

    def unhide(self, key: str):
        with self._lock:
            h = dict(self.settings.get("hidden") or {})
            h.pop(key, None)
            self.settings["hidden"] = h
        self.save()

    def all_rules(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._rules)

    def count(self) -> int:
        with self._lock:
            return len(self._rules)

    def set_setting(self, name: str, value):
        if name in self.settings:
            self.settings[name] = value
            self.save()
