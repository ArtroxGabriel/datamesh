from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DeviceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DEVICE_TYPE_UNKNOWN: _ClassVar[DeviceType]
    AIR_CONDITIONER: _ClassVar[DeviceType]
    TEMPERATURE_SENSOR: _ClassVar[DeviceType]
    RACK_PDU: _ClassVar[DeviceType]

class ClientAction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CLIENT_ACTION_UNKNOWN: _ClassVar[ClientAction]
    LIST_DEVICES: _ClassVar[ClientAction]
    CONTROL_AC: _ClassVar[ClientAction]
    QUERY_ANALYTICS: _ClassVar[ClientAction]
    GET_HISTORY: _ClassVar[ClientAction]

class AnalyticsQueryType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ANALYTICS_QUERY_UNKNOWN: _ClassVar[AnalyticsQueryType]
    HOTTEST_RACK: _ClassVar[AnalyticsQueryType]
    AVG_PDU_POWER: _ClassVar[AnalyticsQueryType]
    THERMAL_STABILITY: _ClassVar[AnalyticsQueryType]
DEVICE_TYPE_UNKNOWN: DeviceType
AIR_CONDITIONER: DeviceType
TEMPERATURE_SENSOR: DeviceType
RACK_PDU: DeviceType
CLIENT_ACTION_UNKNOWN: ClientAction
LIST_DEVICES: ClientAction
CONTROL_AC: ClientAction
QUERY_ANALYTICS: ClientAction
GET_HISTORY: ClientAction
ANALYTICS_QUERY_UNKNOWN: AnalyticsQueryType
HOTTEST_RACK: AnalyticsQueryType
AVG_PDU_POWER: AnalyticsQueryType
THERMAL_STABILITY: AnalyticsQueryType

class DiscoveryRequest(_message.Message):
    __slots__ = ("gateway_ip", "telemetry_udp_port")
    GATEWAY_IP_FIELD_NUMBER: _ClassVar[int]
    TELEMETRY_UDP_PORT_FIELD_NUMBER: _ClassVar[int]
    gateway_ip: str
    telemetry_udp_port: int
    def __init__(self, gateway_ip: _Optional[str] = ..., telemetry_udp_port: _Optional[int] = ...) -> None: ...

class DeviceInfo(_message.Message):
    __slots__ = ("device_id", "device_type", "ip", "grpc_port", "is_online", "state_summary", "last_seen_ms")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_TYPE_FIELD_NUMBER: _ClassVar[int]
    IP_FIELD_NUMBER: _ClassVar[int]
    GRPC_PORT_FIELD_NUMBER: _ClassVar[int]
    IS_ONLINE_FIELD_NUMBER: _ClassVar[int]
    STATE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_MS_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    device_type: DeviceType
    ip: str
    grpc_port: int
    is_online: bool
    state_summary: str
    last_seen_ms: int
    def __init__(self, device_id: _Optional[str] = ..., device_type: _Optional[_Union[DeviceType, str]] = ..., ip: _Optional[str] = ..., grpc_port: _Optional[int] = ..., is_online: _Optional[bool] = ..., state_summary: _Optional[str] = ..., last_seen_ms: _Optional[int] = ...) -> None: ...

class TelemetryPacket(_message.Message):
    __slots__ = ("device_id", "device_type", "timestamp_ms", "is_alert", "temperature_c", "target_temp_c", "fan_speed_pct", "power_watts", "current_amps", "voltage_volts", "ac_power_on")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    IS_ALERT_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    TARGET_TEMP_C_FIELD_NUMBER: _ClassVar[int]
    FAN_SPEED_PCT_FIELD_NUMBER: _ClassVar[int]
    POWER_WATTS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_AMPS_FIELD_NUMBER: _ClassVar[int]
    VOLTAGE_VOLTS_FIELD_NUMBER: _ClassVar[int]
    AC_POWER_ON_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    device_type: DeviceType
    timestamp_ms: int
    is_alert: bool
    temperature_c: float
    target_temp_c: float
    fan_speed_pct: int
    power_watts: float
    current_amps: float
    voltage_volts: float
    ac_power_on: bool
    def __init__(self, device_id: _Optional[str] = ..., device_type: _Optional[_Union[DeviceType, str]] = ..., timestamp_ms: _Optional[int] = ..., is_alert: _Optional[bool] = ..., temperature_c: _Optional[float] = ..., target_temp_c: _Optional[float] = ..., fan_speed_pct: _Optional[int] = ..., power_watts: _Optional[float] = ..., current_amps: _Optional[float] = ..., voltage_volts: _Optional[float] = ..., ac_power_on: _Optional[bool] = ...) -> None: ...

class ACControlRequest(_message.Message):
    __slots__ = ("device_id", "power_on", "target_temp_c", "fan_speed_pct")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    POWER_ON_FIELD_NUMBER: _ClassVar[int]
    TARGET_TEMP_C_FIELD_NUMBER: _ClassVar[int]
    FAN_SPEED_PCT_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    power_on: bool
    target_temp_c: float
    fan_speed_pct: int
    def __init__(self, device_id: _Optional[str] = ..., power_on: _Optional[bool] = ..., target_temp_c: _Optional[float] = ..., fan_speed_pct: _Optional[int] = ...) -> None: ...

class ACControlResponse(_message.Message):
    __slots__ = ("success", "message", "updated_device")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    UPDATED_DEVICE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    updated_device: DeviceInfo
    def __init__(self, success: _Optional[bool] = ..., message: _Optional[str] = ..., updated_device: _Optional[_Union[DeviceInfo, _Mapping]] = ...) -> None: ...

class AnalyticsResult(_message.Message):
    __slots__ = ("query_type", "target_device_id", "primary_value", "secondary_value", "unit", "summary", "sample_count")
    QUERY_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_VALUE_FIELD_NUMBER: _ClassVar[int]
    SECONDARY_VALUE_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    query_type: AnalyticsQueryType
    target_device_id: str
    primary_value: float
    secondary_value: float
    unit: str
    summary: str
    sample_count: int
    def __init__(self, query_type: _Optional[_Union[AnalyticsQueryType, str]] = ..., target_device_id: _Optional[str] = ..., primary_value: _Optional[float] = ..., secondary_value: _Optional[float] = ..., unit: _Optional[str] = ..., summary: _Optional[str] = ..., sample_count: _Optional[int] = ...) -> None: ...

class ClientRequest(_message.Message):
    __slots__ = ("action", "ac_control", "query_type", "window_seconds", "history_limit")
    ACTION_FIELD_NUMBER: _ClassVar[int]
    AC_CONTROL_FIELD_NUMBER: _ClassVar[int]
    QUERY_TYPE_FIELD_NUMBER: _ClassVar[int]
    WINDOW_SECONDS_FIELD_NUMBER: _ClassVar[int]
    HISTORY_LIMIT_FIELD_NUMBER: _ClassVar[int]
    action: ClientAction
    ac_control: ACControlRequest
    query_type: AnalyticsQueryType
    window_seconds: int
    history_limit: int
    def __init__(self, action: _Optional[_Union[ClientAction, str]] = ..., ac_control: _Optional[_Union[ACControlRequest, _Mapping]] = ..., query_type: _Optional[_Union[AnalyticsQueryType, str]] = ..., window_seconds: _Optional[int] = ..., history_limit: _Optional[int] = ...) -> None: ...

class ClientResponse(_message.Message):
    __slots__ = ("success", "message", "devices", "analytics", "history")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DEVICES_FIELD_NUMBER: _ClassVar[int]
    ANALYTICS_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    devices: _containers.RepeatedCompositeFieldContainer[DeviceInfo]
    analytics: AnalyticsResult
    history: _containers.RepeatedCompositeFieldContainer[TelemetryPacket]
    def __init__(self, success: _Optional[bool] = ..., message: _Optional[str] = ..., devices: _Optional[_Iterable[_Union[DeviceInfo, _Mapping]]] = ..., analytics: _Optional[_Union[AnalyticsResult, _Mapping]] = ..., history: _Optional[_Iterable[_Union[TelemetryPacket, _Mapping]]] = ...) -> None: ...
