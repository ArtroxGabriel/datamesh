package main

import (
	"os"
	"testing"
	"time"

	"datamesh/sources/pdu"
)

func TestLoadConfigCustomEnv(t *testing.T) {
	// Arrange
	t.Setenv("PDU_DEVICE_ID", "pdu-rack-99")
	t.Setenv("GATEWAY_HOST", "192.168.1.200")
	t.Setenv("GATEWAY_PORT", "9901")
	t.Setenv("SEND_INTERVAL_SEC", "1.5")
	t.Setenv("MULTICAST_GROUP", "239.255.0.10")
	t.Setenv("MULTICAST_PORT", "9992")
	t.Setenv("BASE_POWER_WATTS", "2100.0")
	t.Setenv("VOLTAGE_VOLTS", "110.0")

	// Act
	cfg := loadConfig()

	// Assert
	if cfg.DeviceID != "pdu-rack-99" {
		t.Errorf("expected DeviceID 'pdu-rack-99', got %s", cfg.DeviceID)
	}
	if cfg.GatewayHost != "192.168.1.200" {
		t.Errorf("expected GatewayHost '192.168.1.200', got %s", cfg.GatewayHost)
	}
	if cfg.GatewayPort != 9901 {
		t.Errorf("expected GatewayPort 9901, got %d", cfg.GatewayPort)
	}
	if cfg.SendInterval != 1500*time.Millisecond {
		t.Errorf("expected SendInterval 1.5s, got %v", cfg.SendInterval)
	}
	if cfg.MulticastGroup != "239.255.0.10" {
		t.Errorf("expected MulticastGroup '239.255.0.10', got %s", cfg.MulticastGroup)
	}
	if cfg.MulticastPort != 9992 {
		t.Errorf("expected MulticastPort 9992, got %d", cfg.MulticastPort)
	}
	if cfg.BasePowerWatts != 2100.0 {
		t.Errorf("expected BasePowerWatts 2100.0, got %f", cfg.BasePowerWatts)
	}
	if cfg.VoltageVolts != 110.0 {
		t.Errorf("expected VoltageVolts 110.0, got %f", cfg.VoltageVolts)
	}
}

func TestLoadConfigDefaults(t *testing.T) {
	// Act
	cfg := loadConfig()

	// Assert
	if cfg.DeviceID != pdu.DefaultDeviceID {
		t.Errorf("expected DefaultDeviceID, got %s", cfg.DeviceID)
	}
	if cfg.GatewayHost != pdu.DefaultGatewayHost {
		t.Errorf("expected DefaultGatewayHost, got %s", cfg.GatewayHost)
	}
	if cfg.GatewayPort != pdu.DefaultGatewayPort {
		t.Errorf("expected DefaultGatewayPort, got %d", cfg.GatewayPort)
	}
}

func TestGetEnvFallbacksOnInvalidTypes(t *testing.T) {
	os.Setenv("TEST_INT", "not-a-number")
	defer os.Unsetenv("TEST_INT")
	if val := getEnvInt("TEST_INT", 42); val != 42 {
		t.Errorf("expected fallback 42, got %d", val)
	}

	os.Setenv("TEST_FLOAT", "not-a-float")
	defer os.Unsetenv("TEST_FLOAT")
	if val := getEnvFloat("TEST_FLOAT", 3.14); val != 3.14 {
		t.Errorf("expected fallback 3.14, got %f", val)
	}
}
