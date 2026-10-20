import datamesh_pb2


def test_serializes_and_deserializes_discovery_messages() -> None:
    # Arrange
    request = datamesh_pb2.DiscoveryRequest(gateway_ip="127.0.0.1", telemetry_udp_port=9998)
    device = datamesh_pb2.DeviceInfo(
        device_id="ac-rack-01",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        ip="127.0.0.1",
        grpc_port=50051,
        is_online=True,
        state_summary="ON | Setpoint: 20.0C | Fan: 80%",
    )

    # Act
    restored_req = datamesh_pb2.DiscoveryRequest.FromString(request.SerializeToString())
    restored_dev = datamesh_pb2.DeviceInfo.FromString(device.SerializeToString())

    # Assert
    assert restored_req.gateway_ip == "127.0.0.1"
    assert restored_req.telemetry_udp_port == 9998
    assert restored_dev.device_id == "ac-rack-01"
    assert restored_dev.device_type == datamesh_pb2.AIR_CONDITIONER
    assert restored_dev.grpc_port == 50051


def test_serializes_and_deserializes_telemetry_packet_with_alert_flag() -> None:
    # Arrange
    packet = datamesh_pb2.TelemetryPacket(
        device_id="temp-rack-02",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=1760000000000,
        is_alert=True,
        temperature_c=38.5,
    )

    # Act
    restored = datamesh_pb2.TelemetryPacket.FromString(packet.SerializeToString())

    # Assert
    assert restored.device_id == "temp-rack-02"
    assert restored.is_alert is True
    assert abs(restored.temperature_c - 38.5) < 1e-4


def test_serializes_and_deserializes_ac_control_messages() -> None:
    # Arrange
    cmd = datamesh_pb2.ACControlRequest(
        device_id="ac-rack-01",
        power_on=True,
        target_temp_c=18.5,
        fan_speed_pct=90,
    )

    # Act
    restored = datamesh_pb2.ACControlRequest.FromString(cmd.SerializeToString())

    # Assert
    assert restored.device_id == "ac-rack-01"
    assert restored.power_on is True
    assert abs(restored.target_temp_c - 18.5) < 1e-4
    assert restored.fan_speed_pct == 90


def test_serializes_and_deserializes_client_gateway_protocol() -> None:
    # Arrange
    client_req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.QUERY_ANALYTICS,
        query_type=datamesh_pb2.HOTTEST_RACK,
        window_seconds=3600,
    )
    client_resp = datamesh_pb2.ClientResponse(
        success=True,
        message="Rack temp-rack-02 recorded 38.5C",
        analytics=datamesh_pb2.AnalyticsResult(
            query_type=datamesh_pb2.HOTTEST_RACK,
            target_device_id="temp-rack-02",
            primary_value=38.5,
            secondary_value=0.0,
            unit="C",
            summary="Peak temperature at temp-rack-02: 38.5 °C",
        ),
    )

    # Act
    restored_req = datamesh_pb2.ClientRequest.FromString(client_req.SerializeToString())
    restored_resp = datamesh_pb2.ClientResponse.FromString(client_resp.SerializeToString())

    # Assert
    assert restored_req.action == datamesh_pb2.QUERY_ANALYTICS
    assert restored_req.query_type == datamesh_pb2.HOTTEST_RACK
    assert restored_resp.success is True
    assert restored_resp.analytics.target_device_id == "temp-rack-02"
