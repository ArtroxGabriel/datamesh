package pdu

import (
	"context"
	"fmt"
	"log"
	"math/rand"
	"net"
	"sync"
	"time"

	datameshpb "datamesh/gen/go"
	"google.golang.org/protobuf/proto"
)

const (
	DefaultDeviceID = "pdu-rack-01"
	// Empty on purpose, so the PDU only streams after it finds the Gateway through
	// multicast discovery. Set GATEWAY_HOST to pin a fixed address instead.
	DefaultGatewayHost    = ""
	DefaultGatewayPort    = 9998
	DefaultSendInterval   = 3 * time.Second
	DefaultMulticastGroup = "239.255.0.1"
	DefaultMulticastPort  = 9999
	DefaultBasePowerWatts = 1400.0
	DefaultVoltageVolts   = 220.0
	MaxDatagramBytes      = 2048
)

// UDPPacketSender abstracts UDP datagram transmission for testing and decoupling.
type UDPPacketSender interface {
	SendTo(data []byte, addr *net.UDPAddr) (int, error)
}

// NetUDPSender transmits packets using a live OS UDP connection.
type NetUDPSender struct {
	conn *net.UDPConn
}

// NewNetUDPSender constructs a production UDP sender.
func NewNetUDPSender() (*NetUDPSender, error) {
	conn, err := net.ListenUDP("udp4", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to bind local UDP socket: %w", err)
	}
	return &NetUDPSender{conn: conn}, nil
}

// SendTo transmits raw datagram bytes to the target UDP address.
func (s *NetUDPSender) SendTo(data []byte, addr *net.UDPAddr) (int, error) {
	return s.conn.WriteToUDP(data, addr)
}

// Close closes the underlying OS UDP socket.
func (s *NetUDPSender) Close() error {
	return s.conn.Close()
}

// Config stores configuration options for the Rack PDU.
type Config struct {
	DeviceID       string
	GatewayHost    string
	GatewayPort    int
	SendInterval   time.Duration
	MulticastGroup string
	MulticastPort  int
	BasePowerWatts float64
	VoltageVolts   float64
}

// PDU represents a Rack Power Distribution Unit data source.
type PDU struct {
	mu          sync.RWMutex
	cfg         Config
	gatewayAddr *net.UDPAddr
	sender      UDPPacketSender
}

// NewPDU constructs a PDU instance with validated defaults and network endpoints.
// Without GatewayHost the gateway address stays unknown until a discovery beacon arrives.
func NewPDU(cfg Config, sender UDPPacketSender) (*PDU, error) {
	resolvedCfg := applyDefaults(cfg)
	unit := &PDU{cfg: resolvedCfg, sender: sender}
	if resolvedCfg.GatewayHost == "" {
		return unit, nil
	}

	gwAddr, err := net.ResolveUDPAddr(
		"udp4",
		fmt.Sprintf("%s:%d", resolvedCfg.GatewayHost, resolvedCfg.GatewayPort),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to resolve gateway address: %w", err)
	}
	unit.gatewayAddr = gwAddr
	return unit, nil
}

func applyDefaults(c Config) Config {
	if c.DeviceID == "" {
		c.DeviceID = DefaultDeviceID
	}
	if c.GatewayPort <= 0 {
		c.GatewayPort = DefaultGatewayPort
	}
	if c.SendInterval <= 0 {
		c.SendInterval = DefaultSendInterval
	}
	if c.MulticastGroup == "" {
		c.MulticastGroup = DefaultMulticastGroup
	}
	if c.MulticastPort <= 0 {
		c.MulticastPort = DefaultMulticastPort
	}
	if c.BasePowerWatts <= 0 {
		c.BasePowerWatts = DefaultBasePowerWatts
	}
	if c.VoltageVolts <= 0 {
		c.VoltageVolts = DefaultVoltageVolts
	}
	return c
}

// GatewayEndpoint returns the currently targeted host and UDP port, or ("", 0) before discovery.
func (p *PDU) GatewayEndpoint() (string, int) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if p.gatewayAddr == nil {
		return "", 0
	}
	return p.gatewayAddr.IP.String(), p.gatewayAddr.Port
}

// CreateTelemetryPacket generates a simulated PDU reading with realistic electrical jitter.
func (p *PDU) CreateTelemetryPacket() *datameshpb.TelemetryPacket {
	p.mu.RLock()
	basePower := p.cfg.BasePowerWatts
	voltage := p.cfg.VoltageVolts
	deviceID := p.cfg.DeviceID
	p.mu.RUnlock()

	jitter := (rand.Float64() - 0.5) * 50.0 // +/- 25 Watts
	power := basePower + jitter
	current := power / voltage

	return &datameshpb.TelemetryPacket{
		DeviceId:     deviceID,
		DeviceType:   datameshpb.DeviceType_RACK_PDU,
		TimestampMs:  time.Now().UnixMilli(),
		IsAlert:      false,
		PowerWatts:   power,
		CurrentAmps:  current,
		VoltageVolts: voltage,
	}
}

// SendTelemetry serializes and sends a telemetry packet to the current Gateway endpoint.
// It does nothing while the gateway is still unknown.
func (p *PDU) SendTelemetry() error {
	p.mu.RLock()
	target := p.gatewayAddr
	p.mu.RUnlock()
	if target == nil {
		return nil
	}

	packet := p.CreateTelemetryPacket()
	payload, err := proto.Marshal(packet)
	if err != nil {
		return fmt.Errorf("failed to marshal telemetry packet: %w", err)
	}

	if _, err := p.sender.SendTo(payload, target); err != nil {
		return fmt.Errorf("failed to transmit UDP packet to %v: %w", target, err)
	}
	return nil
}

// CreateDeviceInfo builds the announcement DeviceInfo payload for this PDU.
func (p *PDU) CreateDeviceInfo() *datameshpb.DeviceInfo {
	p.mu.RLock()
	deviceID := p.cfg.DeviceID
	basePower := p.cfg.BasePowerWatts
	p.mu.RUnlock()

	return &datameshpb.DeviceInfo{
		DeviceId:     deviceID,
		DeviceType:   datameshpb.DeviceType_RACK_PDU,
		IsOnline:     true,
		LastSeenMs:   time.Now().UnixMilli(),
		StateSummary: fmt.Sprintf("Online | Nominal Power: %.0f W", basePower),
	}
}

// HandleDiscoveryRequest updates the targeted Gateway endpoint and replies with DeviceInfo.
func (p *PDU) HandleDiscoveryRequest(data []byte) (*datameshpb.DeviceInfo, error) {
	beacon := &datameshpb.DiscoveryRequest{}
	if err := proto.Unmarshal(data, beacon); err != nil {
		return nil, fmt.Errorf("failed to unmarshal discovery request: %w", err)
	}

	newAddr, err := net.ResolveUDPAddr(
		"udp4",
		fmt.Sprintf("%s:%d", beacon.GetGatewayIp(), beacon.GetTelemetryUdpPort()),
	)
	if err != nil {
		return nil, fmt.Errorf("invalid beacon gateway endpoint: %w", err)
	}

	p.mu.Lock()
	p.gatewayAddr = newAddr
	p.mu.Unlock()

	info := p.CreateDeviceInfo()
	payload, err := proto.Marshal(info)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal device info: %w", err)
	}

	if _, err := p.sender.SendTo(payload, newAddr); err != nil {
		return nil, fmt.Errorf("failed to send announcement to gateway: %w", err)
	}

	log.Printf("[PDU] Discovered Gateway at %s:%d. Sent announcement.",
		beacon.GetGatewayIp(), beacon.GetTelemetryUdpPort())
	return info, nil
}

// StartStreaming begins periodic telemetry streaming until the context is cancelled.
func (p *PDU) StartStreaming(ctx context.Context) {
	p.mu.RLock()
	interval := p.cfg.SendInterval
	p.mu.RUnlock()

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	// Initial packet on startup
	if err := p.SendTelemetry(); err != nil {
		log.Printf("[PDU] Error sending initial telemetry: %v", err)
	}

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := p.SendTelemetry(); err != nil {
				log.Printf("[PDU] Error sending periodic telemetry: %v", err)
			}
		}
	}
}

// StartMulticastListener joins the multicast group to dynamically detect Gateway beacons.
func (p *PDU) StartMulticastListener(ctx context.Context) {
	p.mu.RLock()
	mcastGroup := p.cfg.MulticastGroup
	mcastPort := p.cfg.MulticastPort
	p.mu.RUnlock()

	gaddr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", mcastGroup, mcastPort))
	if err != nil {
		log.Printf("[PDU] Multicast resolve failed: %v", err)
		return
	}

	conn, err := net.ListenMulticastUDP("udp4", nil, gaddr)
	if err != nil {
		log.Printf("[PDU] Multicast bind failed: %v. Using static gateway fallback.", err)
		return
	}
	defer conn.Close()

	buf := make([]byte, MaxDatagramBytes)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
			n, _, err := conn.ReadFrom(buf)
			if err != nil {
				continue
			}
			if _, err := p.HandleDiscoveryRequest(buf[:n]); err != nil {
				log.Printf("[PDU] Malformed beacon received: %v", err)
			}
		}
	}
}
