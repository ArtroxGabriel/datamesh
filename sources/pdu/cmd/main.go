package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"datamesh/sources/pdu"
)

func loadConfig() pdu.Config {
	cfg := pdu.Config{
		DeviceID:       getEnv("PDU_DEVICE_ID", pdu.DefaultDeviceID),
		GatewayHost:    getEnv("GATEWAY_HOST", pdu.DefaultGatewayHost),
		GatewayPort:    getEnvInt("GATEWAY_PORT", pdu.DefaultGatewayPort),
		SendInterval:   time.Duration(getEnvFloat("SEND_INTERVAL_SEC", 3.0) * float64(time.Second)),
		MulticastGroup: getEnv("MULTICAST_GROUP", pdu.DefaultMulticastGroup),
		MulticastPort:  getEnvInt("MULTICAST_PORT", pdu.DefaultMulticastPort),
		BasePowerWatts: getEnvFloat("BASE_POWER_WATTS", pdu.DefaultBasePowerWatts),
		VoltageVolts:   getEnvFloat("VOLTAGE_VOLTS", pdu.DefaultVoltageVolts),
	}
	return cfg
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func getEnvInt(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		if parsed, err := strconv.Atoi(val); err == nil {
			return parsed
		}
	}
	return defaultVal
}

func getEnvFloat(key string, defaultVal float64) float64 {
	if val := os.Getenv(key); val != "" {
		if parsed, err := strconv.ParseFloat(val, 64); err == nil {
			return parsed
		}
	}
	return defaultVal
}

func main() {
	cfg := loadConfig()
	sender, err := pdu.NewNetUDPSender()
	if err != nil {
		log.Fatalf("Fatal: %v", err)
	}
	defer sender.Close()

	unit, err := pdu.NewPDU(cfg, sender)
	if err != nil {
		log.Fatalf("Fatal: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	log.Printf("[PDU] %s started. Target: %s:%d, Interval: %v, Multicast: %s:%d",
		cfg.DeviceID, cfg.GatewayHost, cfg.GatewayPort, cfg.SendInterval,
		cfg.MulticastGroup, cfg.MulticastPort)

	go unit.StartMulticastListener(ctx)
	unit.StartStreaming(ctx)

	log.Printf("[PDU] %s stopped cleanly.", cfg.DeviceID)
}
