"""
core_audio.py — Windows Core Audio (WASAPI) 纯 ctypes/comtypes 封装

提供：
  * 枚举音频端点（渲染/采集），读友好名、形态、默认标记
  * 枚举每个进程的音频会话，读进程名/图标/音量/静音
  * 按进程持久化端点（Win10 1803+ 的 AudioPolicyConfig，即"应用音量和设备首选项"）
  * 设置系统默认端点（IPolicyConfig）

不依赖 pycaw；只用 comtypes + ctypes。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import (
    POINTER, Structure, WINFUNCTYPE, byref, c_float, c_int, c_long, c_uint32,
    c_ulong, c_ushort, c_void_p, c_wchar_p, sizeof,
)
from dataclasses import dataclass, field
from typing import Iterable

import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown, CoCreateInstance

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
CLSID_PolicyConfigClient = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")

eRender, eCapture, eAll = 0, 1, 2
eConsole, eMultimedia, eCommunications = 0, 1, 2

DEVICE_STATE_ACTIVE = 0x1
DEVICE_STATE_ALL = 0xF
STGM_READ = 0

# 设备接口类 GUID（用于 AudioPolicyConfig 的 SWD 端点路径）
DEVINTERFACE_AUDIO_RENDER = "{e6327cad-dcec-4949-ae8a-991e976a79d2}"
DEVINTERFACE_AUDIO_CAPTURE = "{2eef81be-33fa-4800-9670-1cd474972c3f}"

# PROPERTYKEY
PKEY_Device_FriendlyName = (GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}"), 14)
PKEY_Device_DeviceDesc = (GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}"), 2)
PKEY_DeviceInterface_FriendlyName = (GUID("{026e516e-b814-414b-83cd-856d6fef4822}"), 2)
PKEY_AudioEndpoint_FormFactor = (GUID("{1da5d803-d492-4edd-8c23-e0c0ffee7f0e}"), 0)

FORM_FACTOR = {
    0: "网络设备", 1: "扬声器", 2: "线路输出", 3: "耳机", 4: "麦克风",
    5: "耳麦", 6: "话机", 7: "数字直通", 8: "SPDIF", 9: "HDMI",
    10: "未知设备",
}

VT_UI4 = 19
VT_LPWSTR = 31


# --------------------------------------------------------------------------- #
# 结构体
# --------------------------------------------------------------------------- #
class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


class PROPVARIANT(Structure):
    """x64 = 24 字节 / x86 = 16 字节，只关心 VT_LPWSTR / VT_UI4。"""

    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("pwszVal", c_void_p),
        ("_pad", ctypes.c_byte * 8),
    ]


class GUID_(GUID):
    pass


ole32 = ctypes.WinDLL("ole32")
ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
ole32.PropVariantClear.restype = c_long


def _prop_str(pv: PROPVARIANT) -> str | None:
    if pv.vt == VT_LPWSTR and pv.pwszVal:
        return ctypes.wstring_at(pv.pwszVal)
    return None


def _prop_u32(pv: PROPVARIANT) -> int | None:
    if pv.vt == VT_UI4:
        return ctypes.cast(byref(pv, 8), POINTER(c_uint32)).contents.value
    return None


# --------------------------------------------------------------------------- #
# COM 接口
# --------------------------------------------------------------------------- #
class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate",
                  (['in'], POINTER(GUID), 'iid'),
                  (['in'], c_uint32, 'dwClsCtx'),
                  (['in'], c_void_p, 'pActivationParams'),
                  (['out'], POINTER(POINTER(IUnknown)), 'ppInterface')),
        COMMETHOD([], HRESULT, "OpenPropertyStore",
                  (['in'], c_uint32, 'stgmAccess'),
                  (['out'], POINTER(POINTER(IUnknown)), 'ppProperties')),
        COMMETHOD([], HRESULT, "GetId",
                  (['out'], POINTER(c_wchar_p), 'ppstrId')),
        COMMETHOD([], HRESULT, "GetState",
                  (['out'], POINTER(c_uint32), 'pdwState')),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (['out'], POINTER(c_uint32), 'pcDevices')),
        COMMETHOD([], HRESULT, "Item",
                  (['in'], c_uint32, 'nDevice'),
                  (['out'], POINTER(POINTER(IMMDevice)), 'ppDevice')),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                  (['in'], c_int, 'dataFlow'),
                  (['in'], c_uint32, 'dwStateMask'),
                  (['out'], POINTER(POINTER(IMMDeviceCollection)), 'ppDevices')),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                  (['in'], c_int, 'dataFlow'),
                  (['in'], c_int, 'role'),
                  (['out'], POINTER(POINTER(IMMDevice)), 'ppEndpoint')),
        COMMETHOD([], HRESULT, "GetDevice",
                  (['in'], c_wchar_p, 'pwstrId'),
                  (['out'], POINTER(POINTER(IMMDevice)), 'ppDevice')),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback",
                  (['in'], c_void_p, 'pClient')),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback",
                  (['in'], c_void_p, 'pClient')),
    ]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (['out'], POINTER(c_uint32), 'cProps')),
        COMMETHOD([], HRESULT, "GetAt",
                  (['in'], c_uint32, 'iProp'),
                  (['out'], POINTER(PROPERTYKEY), 'pkey')),
        COMMETHOD([], HRESULT, "GetValue",
                  (['in'], POINTER(PROPERTYKEY), 'key'),
                  (['in'], POINTER(PROPVARIANT), 'pv')),
        COMMETHOD([], HRESULT, "SetValue",
                  (['in'], POINTER(PROPERTYKEY), 'key'),
                  (['in'], POINTER(PROPVARIANT), 'propvar')),
        COMMETHOD([], HRESULT, "Commit"),
    ]


class ISimpleAudioVolume(IUnknown):
    _iid_ = GUID("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "SetMasterVolume",
                  (['in'], c_float, 'fLevel'),
                  (['in'], POINTER(GUID), 'EventContext')),
        COMMETHOD([], HRESULT, "GetMasterVolume",
                  (['out'], POINTER(c_float), 'pfLevel')),
        COMMETHOD([], HRESULT, "SetMute",
                  (['in'], c_int, 'bMute'),
                  (['in'], POINTER(GUID), 'EventContext')),
        COMMETHOD([], HRESULT, "GetMute",
                  (['out'], POINTER(c_int), 'pbMute')),
    ]


class IAudioEndpointVolume(IUnknown):
    """设备级音量（系统音量）。"""

    _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
    _methods_ = [
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (['in'], c_void_p, 'pNotify')),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (['in'], c_void_p, 'pNotify')),
        COMMETHOD([], HRESULT, "GetChannelCount", (['out'], POINTER(c_uint32), 'pnChannelCount')),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevel",
                  (['in'], c_float, 'fLevelDB'), (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar",
                  (['in'], c_float, 'fLevel'), (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (['out'], POINTER(c_float), 'pfLevelDB')),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (['out'], POINTER(c_float), 'pfLevel')),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevel",
                  (['in'], c_uint32, 'nChannel'), (['in'], c_float, 'fLevelDB'),
                  (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar",
                  (['in'], c_uint32, 'nChannel'), (['in'], c_float, 'fLevel'),
                  (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevel",
                  (['in'], c_uint32, 'nChannel'), (['out'], POINTER(c_float), 'pfLevelDB')),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar",
                  (['in'], c_uint32, 'nChannel'), (['out'], POINTER(c_float), 'pfLevel')),
        COMMETHOD([], HRESULT, "SetMute",
                  (['in'], c_int, 'bMute'), (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "GetMute", (['out'], POINTER(c_int), 'pbMute')),
        COMMETHOD([], HRESULT, "GetVolumeStepInfo",
                  (['out'], POINTER(c_uint32), 'pnStep'), (['out'], POINTER(c_uint32), 'pnStepCount')),
        COMMETHOD([], HRESULT, "VolumeStepUp", (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "VolumeStepDown", (['in'], POINTER(GUID), 'pguidEventContext')),
        COMMETHOD([], HRESULT, "QueryHardwareSupport", (['out'], POINTER(c_uint32), 'pdwHardwareSupportMask')),
        COMMETHOD([], HRESULT, "GetVolumeRange",
                  (['out'], POINTER(c_float), 'pflVolumeMindB'),
                  (['out'], POINTER(c_float), 'pflVolumeMaxdB'),
                  (['out'], POINTER(c_float), 'pflVolumeIncrementdB')),
    ]


class IAudioMeterInformation(IUnknown):
    """会话/设备的实时电平。GetPeakValue 返回 0.0~1.0 的线性峰值。"""

    _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetPeakValue", (['out'], POINTER(c_float), 'pfPeak')),
        COMMETHOD([], HRESULT, "GetMeteringChannelCount", (['out'], POINTER(c_uint32), 'pnChannelCount')),
        COMMETHOD([], HRESULT, "GetChannelsPeakValues",
                  (['in'], c_uint32, 'u32ChannelCount'),
                  (['out'], POINTER(c_float), 'afPeakValues')),
        COMMETHOD([], HRESULT, "QueryHardwareSupport",
                  (['out'], POINTER(c_uint32), 'pdwHardwareSupportMask')),
    ]


class IAudioSessionControl(IUnknown):
    _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetState", (['out'], POINTER(c_int), 'pRetVal')),
        COMMETHOD([], HRESULT, "GetDisplayName", (['out'], POINTER(c_wchar_p), 'pRetVal')),
        COMMETHOD([], HRESULT, "SetDisplayName",
                  (['in'], c_wchar_p, 'v'), (['in'], POINTER(GUID), 'EventContext')),
        COMMETHOD([], HRESULT, "GetIconPath", (['out'], POINTER(c_wchar_p), 'pRetVal')),
        COMMETHOD([], HRESULT, "SetIconPath",
                  (['in'], c_wchar_p, 'v'), (['in'], POINTER(GUID), 'EventContext')),
        COMMETHOD([], HRESULT, "GetGroupingParam", (['out'], POINTER(GUID), 'pRetVal')),
        COMMETHOD([], HRESULT, "SetGroupingParam",
                  (['in'], POINTER(GUID), 'Override'), (['in'], POINTER(GUID), 'EventContext')),
        COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (['in'], c_void_p, 'NewNotifications')),
        COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (['in'], c_void_p, 'NewNotifications')),
    ]


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetSessionIdentifier", (['out'], POINTER(c_wchar_p), 'pRetVal')),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (['out'], POINTER(c_wchar_p), 'pRetVal')),
        COMMETHOD([], HRESULT, "GetProcessId", (['out'], POINTER(c_uint32), 'pRetVal')),
        COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
        COMMETHOD([], HRESULT, "SetDuckingPreference", (['in'], c_int, 'optOut')),
    ]


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (['out'], POINTER(c_int), 'SessionCount')),
        COMMETHOD([], HRESULT, "GetSession",
                  (['in'], c_int, 'SessionIndex'),
                  (['out'], POINTER(POINTER(IAudioSessionControl)), 'Session')),
    ]


class IAudioSessionManager2(IUnknown):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetAudioSessionControl",
                  (['in'], POINTER(GUID), 'AudioSessionGuid'),
                  (['in'], c_uint32, 'StreamFlags'),
                  (['out'], POINTER(POINTER(IAudioSessionControl)), 'SessionControl')),
        COMMETHOD([], HRESULT, "GetSimpleAudioVolume",
                  (['in'], POINTER(GUID), 'AudioSessionGuid'),
                  (['in'], c_uint32, 'StreamFlags'),
                  (['out'], POINTER(POINTER(ISimpleAudioVolume)), 'AudioVolume')),
        COMMETHOD([], HRESULT, "GetSessionEnumerator",
                  (['out'], POINTER(POINTER(IAudioSessionEnumerator)), 'SessionEnum')),
        COMMETHOD([], HRESULT, "RegisterSessionNotification", (['in'], c_void_p, 'SessionNotification')),
        COMMETHOD([], HRESULT, "UnregisterSessionNotification", (['in'], c_void_p, 'SessionNotification')),
        COMMETHOD([], HRESULT, "RegisterDuckNotification",
                  (['in'], c_wchar_p, 'sessionID'), (['in'], c_void_p, 'duckNotification')),
        COMMETHOD([], HRESULT, "UnregisterDuckNotification", (['in'], c_void_p, 'duckNotification')),
    ]


class IPolicyConfig(IUnknown):
    """CPolicyConfigClient。用于把某个端点设为系统默认。

    CLSID = {870af99c-171d-4f9e-af0d-e63df40c2bc9}（CPolicyConfigClient）
    IID   = {f8679f50-850a-41cf-9c72-430f290290c8}（IPolicyConfig, Win7+）
    """

    _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetMixFormat",
                  (['in'], c_wchar_p, 'pszDeviceName'), (['out'], POINTER(c_void_p), 'ppFormat')),
        COMMETHOD([], HRESULT, "GetDeviceFormat",
                  (['in'], c_wchar_p, 'pszDeviceName'), (['in'], c_int, 'bDefault'),
                  (['out'], POINTER(c_void_p), 'ppFormat')),
        COMMETHOD([], HRESULT, "ResetDeviceFormat", (['in'], c_wchar_p, 'pszDeviceName')),
        COMMETHOD([], HRESULT, "SetDeviceFormat",
                  (['in'], c_wchar_p, 'pszDeviceName'),
                  (['in'], c_void_p, 'pEndpointFormat'),
                  (['in'], c_void_p, 'pMixFormat')),
        COMMETHOD([], HRESULT, "GetProcessingPeriod",
                  (['in'], c_wchar_p, 'pszDeviceName'), (['in'], c_int, 'bDefault'),
                  (['out'], POINTER(ctypes.c_int64), 'pmftDefaultPeriod'),
                  (['out'], POINTER(ctypes.c_int64), 'pmftMinimumPeriod')),
        COMMETHOD([], HRESULT, "SetProcessingPeriod",
                  (['in'], c_wchar_p, 'pszDeviceName'),
                  (['in'], POINTER(ctypes.c_int64), 'pmftPeriod')),
        COMMETHOD([], HRESULT, "GetShareMode",
                  (['in'], c_wchar_p, 'pszDeviceName'), (['out'], POINTER(c_int), 'pMode')),
        COMMETHOD([], HRESULT, "SetShareMode",
                  (['in'], c_wchar_p, 'pszDeviceName'), (['in'], POINTER(c_int), 'mode')),
        COMMETHOD([], HRESULT, "GetPropertyValue",
                  (['in'], c_wchar_p, 'pszDeviceName'),
                  (['in'], POINTER(PROPERTYKEY), 'key'),
                  (['out'], POINTER(PROPVARIANT), 'pv')),
        COMMETHOD([], HRESULT, "SetPropertyValue",
                  (['in'], c_wchar_p, 'pszDeviceName'),
                  (['in'], POINTER(PROPERTYKEY), 'key'),
                  (['in'], POINTER(PROPVARIANT), 'pv')),
        COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                  (['in'], c_wchar_p, 'pszDeviceName'),
                  (['in'], c_int, 'role')),
        COMMETHOD([], HRESULT, "SetEndpointVisibility",
                  (['in'], c_wchar_p, 'pszDeviceName'),
                  (['in'], c_int, 'bVisible')),
    ]


# --------------------------------------------------------------------------- #
# WinRT: IAudioPolicyConfigFactory（按进程持久化端点）
# --------------------------------------------------------------------------- #
IAudioPolicyConfigFactory_IID = GUID("{2a59116d-6c4f-45e0-a74f-707e3fef9258}")

_combase = ctypes.WinDLL("combase")
_combase.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
_combase.RoGetActivationFactory.restype = c_long
_combase.WindowsCreateString.argtypes = [c_wchar_p, c_uint32, POINTER(c_void_p)]
_combase.WindowsCreateString.restype = c_long
_combase.WindowsDeleteString.argtypes = [c_void_p]
_combase.WindowsDeleteString.restype = c_long
_combase.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(c_uint32)]
_combase.WindowsGetStringRawBuffer.restype = c_void_p

# 这个 WinRT 类名在不同 Windows 版本/文档里出现过两种写法，按顺序尝试
_POLICY_CONFIG_CLASSES = (
    "Windows.Media.Internal.AudioPolicyConfig",   # CheVolume 用的（实测可用）
    "Windows.Media.Devices.AudioPolicyConfig",
)

# vtable 索引：0-2 IUnknown, 3-5 IInspectable, 6-24 十九个未公开占位, 25/26/27 实际方法
_VT_SET_PERSISTED = 25
_VT_GET_PERSISTED = 26
_VT_CLEAR_ALL = 27


class _HString:
    __slots__ = ("handle",)

    def __init__(self, text: str):
        self.handle = c_void_p()
        hr = _combase.WindowsCreateString(text, len(text), byref(self.handle))
        if hr < 0:
            raise OSError(f"WindowsCreateString failed: 0x{hr & 0xFFFFFFFF:08X}")

    def close(self):
        if self.handle:
            _combase.WindowsDeleteString(self.handle)
            self.handle = c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _hstring_value(ptr: c_void_p) -> str:
    n = c_uint32()
    buf = _combase.WindowsGetStringRawBuffer(ptr, byref(n))
    return ctypes.wstring_at(buf, n.value) if buf else ""


class PolicyConfigFactory:
    """SetPersistedDefaultAudioEndpoint / GetPersistedDefaultAudioEndpoint 的薄封装。"""

    def __init__(self):
        self._ptr = c_void_p()
        self._class_name = None
        last = None
        for name in _POLICY_CONFIG_CLASSES:
            with _HString(name) as hs:
                ptr = c_void_p()
                hr = _combase.RoGetActivationFactory(
                    hs.handle, byref(IAudioPolicyConfigFactory_IID), byref(ptr))
            if hr >= 0 and ptr:
                self._ptr = ptr
                self._class_name = name
                break
            last = hr
        if not self._ptr:
            raise OSError(
                "无法激活 AudioPolicyConfig（需要 Windows 10 1803 及以上）。"
                f"HRESULT=0x{(last or 0) & 0xFFFFFFFF:08X}")
        vtbl = ctypes.cast(self._ptr, POINTER(POINTER(c_void_p))).contents
        self._vtbl = vtbl

    # -- 内部 ---------------------------------------------------------------
    def _call(self, index: int, *argtypes):
        return WINFUNCTYPE(c_long, c_void_p, *argtypes)(self._vtbl[index])

    # -- 公开 ---------------------------------------------------------------
    def set_persisted(self, pid: int, flow: int, role: int, device_id: str) -> None:
        """把 pid 在 flow/role 上的端点设为 device_id（传空串 = 清除）。"""
        swd = swd_endpoint(device_id, flow) if device_id else ""
        with _HString(swd) as hs:
            fn = self._call(_VT_SET_PERSISTED, c_uint32, c_int, c_int, c_void_p)
            hr = fn(self._ptr, c_uint32(pid), c_int(flow), c_int(role), hs.handle)
        if hr < 0:
            raise OSError(f"SetPersistedDefaultAudioEndpoint failed: 0x{hr & 0xFFFFFFFF:08X}")

    def get_persisted(self, pid: int, flow: int, role: int) -> str:
        out = c_void_p()
        fn = self._call(_VT_GET_PERSISTED, c_uint32, c_int, c_int, POINTER(c_void_p))
        hr = fn(self._ptr, c_uint32(pid), c_int(flow), c_int(role), byref(out))
        if hr < 0 or not out:
            return ""
        raw = _hstring_value(out)
        _combase.WindowsDeleteString(out)
        return swd_to_id(raw)

    def clear_all(self) -> None:
        fn = self._call(_VT_CLEAR_ALL)
        hr = fn(self._ptr)
        if hr < 0:
            raise OSError(f"ClearAllPersistedApplicationDefaultEndpoints failed: 0x{hr & 0xFFFFFFFF:08X}")


def swd_endpoint(device_id: str, flow: int) -> str:
    tag = DEVINTERFACE_AUDIO_RENDER if flow == eRender else DEVINTERFACE_AUDIO_CAPTURE
    return f"\\\\?\\SWD#MMDEVAPI#{device_id}#{tag}"


def swd_to_id(swd: str) -> str:
    if not swd:
        return ""
    s = swd
    prefix = "\\\\?\\SWD#MMDEVAPI#"
    if s.startswith(prefix):
        s = s[len(prefix):]
    for tag in (DEVINTERFACE_AUDIO_RENDER, DEVINTERFACE_AUDIO_CAPTURE):
        if s.endswith("#" + tag):
            s = s[: -(len(tag) + 1)]
    return s


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Device:
    id: str
    name: str
    desc: str
    form_factor: str
    flow: int
    is_default: bool = False
    is_default_comms: bool = False
    state: int = DEVICE_STATE_ACTIVE

    @property
    def short_name(self) -> str:
        """只取主名称，去掉括号里的硬件描述。

        "22白色 (2- USBAudio2.0)" -> "22白色"
        "333 (High Definition Audio Device)" -> "333"
        """
        n = (self.name or "").strip()
        if " (" in n:
            head = n.split(" (")[0].strip()
            if head:
                return head
        return n or self.id

    @property
    def subtitle(self) -> str:
        bits = [b for b in (self.form_factor, self.desc) if b]
        return " · ".join(dict.fromkeys(bits))


@dataclass
class Session:
    pid: int
    process_name: str
    exe_path: str
    session_id: str
    instance_id: str
    volume: float
    muted: bool
    is_system: bool
    state: int
    device_id: str = ""          # 这个会话当前挂在哪个渲染设备上
    device_name: str = ""
    _ctl: object = field(default=None, repr=False)
    _vol: object = field(default=None, repr=False)
    _meter: object = field(default=None, repr=False)

    def peak(self) -> float:
        """实时峰值 0.0~1.0（线性）。拿不到就返回 0。"""
        m = self._meter
        if m is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(m.GetPeakValue())))
        except Exception:
            return 0.0

    @property
    def title(self) -> str:
        return self.process_name or (self.exe_path.rsplit("\\", 1)[-1] if self.exe_path else f"PID {self.pid}")


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
class AudioCore:
    def __init__(self):
        self._enum: IMMDeviceEnumerator | None = None
        self._policy: PolicyConfigFactory | None = None
        self._policy_error: str | None = None
        self._dev_ep: dict[str, tuple] = {}

    # -- 生命周期 -----------------------------------------------------------
    def initialize(self):
        comtypes.CoInitialize()
        self._enum = CoCreateInstance(
            CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator, clsctx=CLSCTX_ALL)

    def close(self):
        self._enum = None
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass

    @property
    def policy(self) -> PolicyConfigFactory:
        if self._policy is None:
            if self._policy_error:
                raise OSError(self._policy_error)
            try:
                self._policy = PolicyConfigFactory()
            except Exception as exc:
                self._policy_error = str(exc)
                raise
        return self._policy

    @property
    def policy_available(self) -> bool:
        try:
            self.policy
            return True
        except Exception:
            return False

    # -- 设备 ---------------------------------------------------------------
    def _devices_of(self, flow: int, state_mask: int = DEVICE_STATE_ACTIVE) -> list[Device]:
        coll = self._enum.EnumAudioEndpoints(flow, state_mask)
        default_id = ""
        default_comms = ""
        try:
            default_id = self._enum.GetDefaultAudioEndpoint(flow, eConsole).GetId()
        except Exception:
            pass
        try:
            default_comms = self._enum.GetDefaultAudioEndpoint(flow, eCommunications).GetId()
        except Exception:
            pass

        out: list[Device] = []
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            dev_id = dev.GetId()
            name = desc = ""
            ff = 0
            try:
                store = dev.OpenPropertyStore(STGM_READ)
                props = store.QueryInterface(IPropertyStore)
                name = self._get_str(props, PKEY_Device_FriendlyName) or ""
                desc = self._get_str(props, PKEY_Device_DeviceDesc) or ""
                if not name:
                    name = self._get_str(props, PKEY_DeviceInterface_FriendlyName) or ""
                ff = self._get_u32(props, PKEY_AudioEndpoint_FormFactor) or 0
            except Exception:
                pass
            out.append(Device(
                id=dev_id, name=name or dev_id, desc=desc,
                form_factor=FORM_FACTOR.get(ff, ""), flow=flow,
                is_default=(dev_id == default_id),
                is_default_comms=(dev_id == default_comms),
            ))
        return out

    @staticmethod
    def _get_str(store: IPropertyStore, key: tuple) -> str | None:
        pk = PROPERTYKEY(key[0], key[1])
        pv = PROPVARIANT()
        store.GetValue(byref(pk), byref(pv))
        try:
            return _prop_str(pv)
        finally:
            ole32.PropVariantClear(byref(pv))

    @staticmethod
    def _get_u32(store: IPropertyStore, key: tuple) -> int | None:
        pk = PROPERTYKEY(key[0], key[1])
        pv = PROPVARIANT()
        store.GetValue(byref(pk), byref(pv))
        try:
            return _prop_u32(pv)
        finally:
            ole32.PropVariantClear(byref(pv))

    def output_devices(self) -> list[Device]:
        return self._devices_of(eRender)

    def input_devices(self) -> list[Device]:
        return self._devices_of(eCapture)

    def device_endpoint(self, device_id: str):
        """返回 (IAudioEndpointVolume, IAudioMeterInformation)，带缓存。"""
        if device_id in self._dev_ep:
            return self._dev_ep[device_id]
        vol = meter = None
        try:
            dev = self._enum.GetDevice(device_id)
            try:
                vol = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None) \
                    .QueryInterface(IAudioEndpointVolume)
            except Exception:
                vol = None
            try:
                meter = dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None) \
                    .QueryInterface(IAudioMeterInformation)
            except Exception:
                meter = None
        except Exception:
            pass
        self._dev_ep[device_id] = (vol, meter)
        return vol, meter

    def device_volume(self, device_id: str) -> float:
        vol, _ = self.device_endpoint(device_id)
        if vol is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(vol.GetMasterVolumeLevelScalar())))
        except Exception:
            return 0.0

    def set_device_volume(self, device_id: str, level: float) -> None:
        vol, _ = self.device_endpoint(device_id)
        if vol is None:
            return
        try:
            vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(level))), None)
        except Exception:
            pass

    def device_peak(self, device_id: str) -> float:
        _, meter = self.device_endpoint(device_id)
        if meter is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(meter.GetPeakValue())))
        except Exception:
            return 0.0

    def get_default_id(self, flow: int = eRender, role: int = eConsole) -> str:
        """只取默认设备 ID，开销极小，用于高频轮询检测默认设备有没有被改。"""
        try:
            return self._enum.GetDefaultAudioEndpoint(flow, role).GetId() or ""
        except Exception:
            return ""

    def set_system_default(self, device_id: str, role: int = eConsole,
                           clear_first: bool = False) -> None:
        """把端点设为系统默认。

        Windows 的行为：只要系统里存在任何「按应用的设备设置」，同线程再调
        IPolicyConfig::SetDefaultEndpoint 就会静默失效（返回 S_OK 但默认设备不变）。
        所以要让默认切换生效，必须先 ClearAllPersistedApplicationDefaultEndpoints，
        代价是清空所有应用级记忆（调用方负责备份并重新套用）。
        """
        if clear_first:
            try:
                self.policy.clear_all()
            except Exception:
                pass
        pc = CoCreateInstance(CLSID_PolicyConfigClient, interface=IPolicyConfig, clsctx=CLSCTX_ALL)
        pc.SetDefaultEndpoint(device_id, role)

    # -- 会话 ---------------------------------------------------------------
    def sessions(self, flow: int = eRender) -> list[Session]:
        result: list[Session] = []
        try:
            coll = self._enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
        except Exception:
            return result

        by_key: dict[str, Session] = {}
        for i in range(coll.GetCount()):
            try:
                dev = coll.Item(i)
                dev_id = dev.GetId() or ""
                unk = dev.Activate(byref(IAudioSessionManager2._iid_), CLSCTX_ALL, None)
                mgr = unk.QueryInterface(IAudioSessionManager2)
            except Exception:
                continue
            try:
                enum = mgr.GetSessionEnumerator()
            except Exception:
                continue
            try:
                count = enum.GetCount()
            except Exception:
                continue

            for idx in range(count):
                try:
                    ctl_raw = enum.GetSession(idx)
                except Exception:
                    continue
                try:
                    ctl2 = ctl_raw.QueryInterface(IAudioSessionControl2)
                except Exception:
                    continue
                try:
                    pid = ctl2.GetProcessId()
                except Exception:
                    continue
                try:
                    is_sys = ctl2.IsSystemSoundsSession() == 0
                except Exception:
                    is_sys = False

                try:
                    state = ctl2.GetState()
                except Exception:
                    state = 0

                # 同一进程只保留一行（它在多个设备上的会话会镜像出现）。
                # 优先保留真正在发声（Active=1）的那个，它的设备才是"当前在用的"。
                key = "sys" if is_sys else f"pid:{pid}"
                prev = by_key.get(key)
                if prev is not None and not (state == 1 and prev.state != 1):
                    continue
                if prev is not None:
                    prev._vol = None
                    prev._ctl = None
                    prev._meter = None

                try:
                    inst = ctl2.GetSessionInstanceIdentifier() or ""
                except Exception:
                    inst = ""

                vol_obj = None
                volume, muted = 1.0, False
                try:
                    gp = ctl2.GetGroupingParam()
                    vol_obj = mgr.GetSimpleAudioVolume(byref(gp), 0)
                    volume = float(vol_obj.GetMasterVolume())
                    muted = bool(vol_obj.GetMute())
                except Exception:
                    vol_obj = None

                meter_obj = None
                try:
                    meter_obj = ctl2.QueryInterface(IAudioMeterInformation)
                except Exception:
                    meter_obj = None

                exe, pname = _process_info(pid)
                by_key[key] = Session(
                    pid=pid, process_name=pname, exe_path=exe,
                    session_id=_safe(lambda: ctl2.GetSessionIdentifier(), "") or "",
                    instance_id=inst, volume=volume, muted=muted,
                    is_system=is_sys, state=state,
                    device_id=dev_id,
                    _ctl=ctl2, _vol=vol_obj, _meter=meter_obj,
                )
        result = list(by_key.values())
        result.sort(key=lambda s: (s.is_system, s.process_name.lower()))
        return result

    # -- 按进程路由 ---------------------------------------------------------
    def route_process(self, pid: int, device_id: str, flow: int = eRender) -> bool:
        """把 pid 的 flow 端点设为 device_id；device_id 为空表示恢复默认。

        返回是否至少有一个角色设置成功。Windows 对「系统里还没有该应用的
        设备记录」的进程会返回 E_ACCESSDENIED，这里逐个角色尝试并汇总。
        """
        factory = self.policy
        ok = False
        last: Exception | None = None
        for role in (eConsole, eMultimedia):
            try:
                factory.set_persisted(pid, flow, role, device_id)
                ok = True
            except Exception as exc:
                last = exc
        if not ok and last is not None:
            raise last
        return ok

    def get_route(self, pid: int, flow: int = eRender) -> str:
        try:
            return self.policy.get_persisted(pid, flow, eConsole)
        except Exception:
            return ""

    # -- 音量 ---------------------------------------------------------------
    @staticmethod
    def set_session_volume(session: Session, level: float) -> None:
        if session._vol is not None:
            session._vol.SetMasterVolume(max(0.0, min(1.0, float(level))), None)

    @staticmethod
    def set_session_mute(session: Session, mute: bool) -> None:
        if session._vol is not None:
            session._vol.SetMute(1 if mute else 0, None)


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


_PROC_CACHE: dict[int, tuple[str, str]] = {}


def _process_info(pid: int) -> tuple[str, str]:
    """返回 (exe 全路径, 进程名不含扩展名)。"""
    if pid == 0:
        return (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "audiodg.exe"),
                "系统声音")
    if pid in _PROC_CACHE:
        return _PROC_CACHE[pid]
    exe, name = "", f"PID {pid}"
    try:
        import psutil
        p = psutil.Process(pid)
        exe = p.exe() or ""
        name = p.name()
        if name.lower().endswith(".exe"):
            name = name[:-4]
    except Exception:
        try:
            import ctypes.wintypes as wt
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.argtypes = [c_uint32, c_int, c_uint32]
            k32.OpenProcess.restype = c_void_p
            k32.QueryFullProcessImageNameW.argtypes = [c_void_p, c_uint32, c_wchar_p, POINTER(c_uint32)]
            k32.QueryFullProcessImageNameW.restype = c_int
            k32.CloseHandle.argtypes = [c_void_p]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = c_uint32(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
                        exe = buf.value
                        name = os.path.basename(exe)
                        if name.lower().endswith(".exe"):
                            name = name[:-4]
                finally:
                    k32.CloseHandle(h)
        except Exception:
            pass
    if len(_PROC_CACHE) > 512:
        _PROC_CACHE.clear()
    _PROC_CACHE[pid] = (exe, name)
    return exe, name
