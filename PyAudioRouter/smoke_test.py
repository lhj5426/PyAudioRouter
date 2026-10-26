"""非 GUI 冒烟测试：枚举设备、会话，验证 AudioPolicyConfig 可用性。"""
import sys

import audio_core as ac


def main():
    core = ac.AudioCore()
    core.initialize()
    print("=" * 60)
    print("输出设备:")
    outs = core.output_devices()
    for d in outs:
        flag = " [默认]" if d.is_default else (" [通信默认]" if d.is_default_comms else "")
        print(f"  - {d.name}{flag}")
        print(f"      {d.subtitle}  id={d.id}")
    print("=" * 60)
    print("输入设备:")
    for d in core.input_devices():
        flag = " [默认]" if d.is_default else ""
        print(f"  - {d.name}{flag}  {d.subtitle}")
    print("=" * 60)
    print("AudioPolicyConfig 可用:", core.policy_available)
    print("=" * 60)
    sess = core.sessions(ac.eRender)
    print(f"音频会话 ({len(sess)}):")
    for s in sess:
        print(f"  pid={s.pid:6d} {s.title:30s} vol={s.volume:.2f} mute={s.muted} sys={s.is_system}")
        print(f"        exe={s.exe_path}")
    print("=" * 60)
    # 路由读写自测：拿一个真实会话，写入映射再读回，然后恢复
    if core.policy_available and sess:
        target = next((s for s in sess if not s.is_system and s.exe_path), None)
        if target:
            before = core.get_route(target.pid, ac.eRender)
            dev = next((d for d in outs if d.id != before), None)
            if dev:
                print(f"路由自测: pid={target.pid} ({target.title}) -> {dev.name}")
                print("  写入前:", repr(before))
                try:
                    core.route_process(target.pid, dev.id, ac.eRender)
                    after = core.get_route(target.pid, ac.eRender)
                    print("  写入后:", repr(after), "匹配:", after == dev.id)
                    core.route_process(target.pid, before, ac.eRender)
                    restored = core.get_route(target.pid, ac.eRender)
                    print("  恢复后:", repr(restored), "匹配原值:", restored == before)
                except OSError as exc:
                    print("  写入被拒绝:", exc)
                    print("  （该应用在系统里还没有设备记录，属于已知限制）")
    core.close()


if __name__ == "__main__":
    sys.exit(main())
