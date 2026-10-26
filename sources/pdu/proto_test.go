package pdu_test

import (
	"testing"

	datameshpb "datamesh/gen/go"
	"google.golang.org/protobuf/proto"
)

func TestSerializesAndDeserializesPDUTelemetryAndDiscovery(t *testing.T) {
	// Arrange
	original := &datameshpb.TelemetryPacket{
		DeviceId:    "pdu-rack-01",
		DeviceType:  datameshpb.DeviceType_RACK_PDU,
		TimestampMs: 1760000000000,
		Payload: &datameshpb.TelemetryPacket_Pdu{
			Pdu: &datameshpb.PDUTelemetry{
				PowerWatts:   1450.5,
				CurrentAmps:  6.6,
				VoltageVolts: 220.0,
			},
		},
	}

	// Act
	rawBytes, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("expected no error marshaling TelemetryPacket, got: %v", err)
	}

	restored := &datameshpb.TelemetryPacket{}
	if err := proto.Unmarshal(rawBytes, restored); err != nil {
		t.Fatalf("expected no error unmarshaling TelemetryPacket, got: %v", err)
	}

	// Assert
	if restored.GetDeviceId() != "pdu-rack-01" {
		t.Errorf("expected device_id pdu-rack-01, got %s", restored.GetDeviceId())
	}
	if restored.GetDeviceType() != datameshpb.DeviceType_RACK_PDU {
		t.Errorf("expected RACK_PDU, got %v", restored.GetDeviceType())
	}
	if restored.GetPdu().GetPowerWatts() != 1450.5 {
		t.Errorf("expected power_watts 1450.5, got %f", restored.GetPdu().GetPowerWatts())
	}
}
