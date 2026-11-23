package pdu

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAuthenticatedDatagramsAndPersistentReplay(t *testing.T) {
	dir := t.TempDir()
	keys := filepath.Join(dir, "hmac")
	if err := os.Mkdir(keys, 0700); err != nil {
		t.Fatal(err)
	}
	key := []byte("01234567890123456789012345678901")
	for _, name := range []string{"gateway", "pdu"} {
		if err := os.WriteFile(filepath.Join(keys, name+".key"), key, 0600); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("DATAMESH_SECURITY_MODE", "secure")
	t.Setenv("DATAMESH_CREDENTIALS_DIR", dir)
	t.Setenv("DATAMESH_SECURITY_STATE_DIR", filepath.Join(dir, "state"))
	s, err := newSecureDatagrams("pdu")
	if err != nil {
		t.Fatal(err)
	}
	packet, err := s.encode(3, []byte("test"))
	if err != nil {
		t.Fatal(err)
	}
	if string(packet[:4]) != "DMS2" || binary.BigEndian.Uint64(packet[6:14]) != 1 {
		t.Fatal("invalid envelope")
	}
	if bytes.Contains(packet, []byte("test")) {
		t.Fatal("plaintext telemetry exposed")
	}
	mac := hmac.New(sha256.New, key)
	mac.Write(packet[:len(packet)-32])
	if !hmac.Equal(mac.Sum(nil), packet[len(packet)-32:]) {
		t.Fatal("invalid signature")
	}
	sender, err := newSecureDatagrams("gateway")
	if err != nil {
		t.Fatal(err)
	}
	beacon, err := sender.encode(1, []byte("beacon"))
	if err != nil {
		t.Fatal(err)
	}
	tampered := append([]byte(nil), beacon...)
	tampered[len(tampered)-33] ^= 1
	mac = hmac.New(sha256.New, key)
	mac.Write(tampered[:len(tampered)-32])
	copy(tampered[len(tampered)-32:], mac.Sum(nil))
	if _, err := s.discovery(tampered); err == nil {
		t.Fatal("tampered ciphertext accepted")
	}
	if payload, err := s.discovery(beacon); err != nil || string(payload) != "beacon" {
		t.Fatalf("discovery: %q %v", payload, err)
	}
	restarted, err := newSecureDatagrams("pdu")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := restarted.discovery(beacon); err == nil {
		t.Fatal("replay accepted after restart")
	}
	next, err := restarted.encode(3, []byte("next"))
	if err != nil {
		t.Fatal(err)
	}
	if binary.BigEndian.Uint64(next[6:14]) != 2 {
		t.Fatal("sequence not persisted")
	}
	expired := append([]byte(nil), beacon...)
	binary.BigEndian.PutUint64(expired[14:22], uint64(time.Now().Add(-time.Minute).UnixMilli()))
	mac = hmac.New(sha256.New, key)
	mac.Write(expired[:len(expired)-32])
	copy(expired[len(expired)-32:], mac.Sum(nil))
	if _, err := restarted.discovery(expired); err == nil {
		t.Fatal("expired beacon accepted")
	}
}
