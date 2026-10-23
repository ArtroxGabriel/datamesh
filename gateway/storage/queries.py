"""SQL statements and schemas for DataMesh DCIM Gateway storage."""

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    device_type INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    is_alert INTEGER NOT NULL,
    temperature_c REAL,
    target_temp_c REAL,
    fan_speed_pct INTEGER,
    power_watts REAL,
    current_amps REAL,
    voltage_volts REAL,
    ac_power_on INTEGER
);
CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry (timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_telemetry_type_time ON telemetry (device_type, timestamp_ms);
"""

INSERT_TELEMETRY_SQL = """
INSERT INTO telemetry (
    device_id, device_type, timestamp_ms, is_alert,
    temperature_c, target_temp_c, fan_speed_pct,
    power_watts, current_amps, voltage_volts, ac_power_on
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

SELECT_RECENT_HISTORY_SQL = """
SELECT device_id, device_type, timestamp_ms, is_alert,
       temperature_c, target_temp_c, fan_speed_pct,
       power_watts, current_amps, voltage_volts, ac_power_on
FROM telemetry
ORDER BY timestamp_ms DESC
LIMIT ?;
"""

SELECT_HOTTEST_RACK_SQL = """
SELECT
    (SELECT device_id FROM telemetry
     WHERE timestamp_ms >= ? AND temperature_c IS NOT NULL AND temperature_c > 0
     ORDER BY temperature_c DESC LIMIT 1) as hottest_device,
    MAX(temperature_c) as max_temp,
    COUNT(*) as sample_count
FROM telemetry
WHERE timestamp_ms >= ? AND temperature_c IS NOT NULL AND temperature_c > 0;
"""

SELECT_AVG_PDU_POWER_SQL = """
SELECT AVG(power_watts) as avg_power, COUNT(*) as sample_count
FROM telemetry
WHERE device_type = ? AND timestamp_ms >= ? AND power_watts IS NOT NULL;
"""

SELECT_THERMAL_STABILITY_SQL = """
SELECT temperature_c
FROM telemetry
WHERE timestamp_ms >= ? AND temperature_c IS NOT NULL AND temperature_c > 0;
"""
