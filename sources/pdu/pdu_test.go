package pdu_test

import (
	"context"
	"errors"
	"net"
	"sync"
	"testing"
	"time"

	datameshpb "datamesh/gen/go"
	"datamesh/sources/pdu"
	"google.golang.org/protobuf/proto"
)

type FakeUDPSender struct {
	mu      sync.Mutex
	Packets []SentPacket
	Err     error
}

type SentPacket struct {
	Data []byte
	Addr *net.UDPAddr
}

func (f *FakeUDPSender) SendTo(data []byte, addr *net.UDPAddr) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.Err != nil {
		return 0, f.Err
	}
	// Copy data to ensure immutability
	dataCopy := make([]byte, len(data))
	copy(dataCopy, data)
	f.Packets = append(f.Packets, SentPacket{Data: dataCopy, Addr: addr})
	return len(data), nil
}

func (f *FakeUDPSender) SentCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.Packets)
}

func TestCreatesValidTelemetryPacket(t *testing.T) {
	// Arrange
	cfg := pdu.Config{
		DeviceID:       "pdu-rack-01",
		GatewayHost:    "127.0.0.1",
		GatewayPort:    9998,
		BasePowerWatts: 1500.0,
		VoltageVolts:   220.0,
	}
	unit, err := pdu.NewPDU(cfg, &FakeUDPSender{})
	if err != nil {
		t.Fatalf("unexpected NewPDU error: %v", err)
	}

	// Act
	packet := unit.CreateTelemetryPacket()

	// Assert
	if packet.GetDeviceId() != "pdu-rack-01" {
		t.Errorf("expected device_id 'pdu-rack-01', got %s", packet.GetDeviceId())
	}
	if packet.GetDeviceType() != datameshpb.DeviceType_RACK_PDU {
		t.Errorf("expected device_type RACK_PDU, got %v", packet.GetDeviceType())
	}
	if packet.GetPdu().GetVoltageVolts() != 220.0 {
		t.Errorf("expected voltage 220.0V, got %f", packet.GetPdu().GetVoltageVolts())
	}
	if packet.GetPdu().GetPowerWatts() <= 0.0 {
		t.Errorf("expected positive power, got %f", packet.GetPdu().GetPowerWatts())
	}
	if packet.GetPdu().GetCurrentAmps() <= 0.0 {
		t.Errorf("expected positive current, got %f", packet.GetPdu().GetCurrentAmps())
	}
	if packet.GetTimestampMs() <= 0 {
		t.Errorf("expected positive timestamp, got %d", packet.GetTimestampMs())
	}
}

func TestSendTelemetryTransmitsProtobufToGateway(t *testing.T) {
	// Arrange
	sender := &FakeUDPSender{}
	cfg := pdu.Config{
		DeviceID:       "pdu-rack-01",
		GatewayHost:    "127.0.0.1",
		GatewayPort:    9998,
		BasePowerWatts: 1200.0,
		VoltageVolts:   220.0,
	}
	unit, err := pdu.NewPDU(cfg, sender)
	if err != nil {
		t.Fatalf("unexpected NewPDU error: %v", err)
	}

	// Act
	err = unit.SendTelemetry()

	// Assert
	if err != nil {
		t.Fatalf("expected no error sending telemetry, got: %v", err)
	}
	if sender.SentCount() != 1 {
		t.Fatalf("expected 1 sent packet, got %d", sender.SentCount())
	}

	raw := sender.Packets[0]
	if raw.Addr.IP.String() != "127.0.0.1" || raw.Addr.Port != 9998 {
		t.Errorf("expected target 127.0.0.1:9998, got %s:%d", raw.Addr.IP, raw.Addr.Port)
	}

	decoded := &datameshpb.TelemetryPacket{}
	if err := proto.Unmarshal(raw.Data, decoded); err != nil {
		t.Fatalf("expected valid Protobuf packet, got error: %v", err)
	}
	if decoded.GetDeviceId() != "pdu-rack-01" {
		t.Errorf("expected device_id 'pdu-rack-01', got %s", decoded.GetDeviceId())
	}
}

func TestHandleDiscoveryRequestUpdatesGatewayAndReturnsDeviceInfo(t *testing.T) {
	// Arrange
	sender := &FakeUDPSender{}
	cfg := pdu.Config{
		DeviceID:    "pdu-rack-01",
		GatewayHost: "127.0.0.1",
		GatewayPort: 9998,
	}
	unit, err := pdu.NewPDU(cfg, sender)
	if err != nil {
		t.Fatalf("unexpected NewPDU error: %v", err)
	}

	beacon := &datameshpb.DiscoveryRequest{
		GatewayIp:        "192.168.1.50",
		TelemetryUdpPort: 9991,
	}
	beaconBytes, err := proto.Marshal(beacon)
	if err != nil {
		t.Fatalf("failed to marshal beacon: %v", err)
	}

	// Act
	info, err := unit.HandleDiscoveryRequest(beaconBytes)

	// Assert
	if err != nil {
		t.Fatalf("expected no error handling beacon, got: %v", err)
	}
	if info.GetDeviceId() != "pdu-rack-01" {
		t.Errorf("expected device_id 'pdu-rack-01', got %s", info.GetDeviceId())
	}
	if info.GetDeviceType() != datameshpb.DeviceType_RACK_PDU {
		t.Errorf("expected RACK_PDU, got %v", info.GetDeviceType())
	}
	if !info.GetIsOnline() {
		t.Errorf("expected is_online=true")
	}

	// Ensure gateway address was updated and announcement was sent
	gwHost, gwPort := unit.GatewayEndpoint()
	if gwHost != "192.168.1.50" || gwPort != 9991 {
		t.Errorf("expected updated gateway 192.168.1.50:9991, got %s:%d", gwHost, gwPort)
	}
	if sender.SentCount() != 1 {
		t.Fatalf("expected 1 announcement packet sent, got %d", sender.SentCount())
	}
}

func TestHandleDiscoveryRequestReturnsErrorOnInvalidBytes(t *testing.T) {
	// Arrange
	sender := &FakeUDPSender{}
	cfg := pdu.Config{DeviceID: "pdu-rack-01"}
	unit, _ := pdu.NewPDU(cfg, sender)

	// Act
	_, err := unit.HandleDiscoveryRequest([]byte{0xff, 0xff, 0xff, 0xff})

	// Assert
	if err == nil {
		t.Errorf("expected error decoding corrupt discovery request, got nil")
	}
	if sender.SentCount() != 0 {
		t.Errorf("expected 0 packets sent on corrupt discovery, got %d", sender.SentCount())
	}
}

func TestSendTelemetryPropagatesSenderError(t *testing.T) {
	// Arrange
	sender := &FakeUDPSender{Err: errors.New("network unreachable")}
	cfg := pdu.Config{
		DeviceID:    "pdu-rack-01",
		GatewayHost: "127.0.0.1",
		GatewayPort: 9998,
	}
	unit, _ := pdu.NewPDU(cfg, sender)

	// Act
	err := unit.SendTelemetry()

	// Assert
	if err == nil {
		t.Errorf("expected error from failed network sender, got nil")
	}
}

func TestStreamingStopsWhenContextCancelled(t *testing.T) {
	// Arrange
	sender := &FakeUDPSender{}
	cfg := pdu.Config{
		DeviceID:     "pdu-rack-01",
		GatewayHost:  "127.0.0.1",
		GatewayPort:  9998,
		SendInterval: 10 * time.Millisecond,
	}
	unit, _ := pdu.NewPDU(cfg, sender)

	ctx, cancel := context.WithCancel(context.Background())

	// Act
	done := make(chan struct{})
	go func() {
		unit.StartStreaming(ctx)
		close(done)
	}()

	time.Sleep(35 * time.Millisecond)
	cancel()

	select {
	case <-done:
		// Succeeded
	case <-time.After(500 * time.Millisecond):
		t.Fatalf("StartStreaming did not stop after context was cancelled")
	}

	// Assert: At least 2 packets were transmitted
	if sender.SentCount() < 2 {
		t.Errorf("expected at least 2 packets sent, got %d", sender.SentCount())
	}
}
