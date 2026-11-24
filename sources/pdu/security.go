package pdu

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// secureDatagrams implements the same authenticated envelope as common/security.py.
// Source counters are stored separately from the Gateway's SQLite state.
type secureDatagrams struct{ identity, keys, state string }

func newSecureDatagrams(identity string) (*secureDatagrams, error) {
	mode := os.Getenv("DATAMESH_SECURITY_MODE")
	if mode == "" || mode == "insecure" {
		return nil, nil
	}
	if mode != "secure" {
		return nil, errors.New("invalid DATAMESH_SECURITY_MODE")
	}
	if !validIdentity(identity) {
		return nil, errors.New("invalid device identity")
	}
	credentials := os.Getenv("DATAMESH_CREDENTIALS_DIR")
	if credentials == "" {
		credentials = ".datamesh-security"
	}
	state := os.Getenv("DATAMESH_SECURITY_STATE_DIR")
	if state == "" {
		state = ".datamesh-security-state"
	}
	s := &secureDatagrams{identity, filepath.Join(credentials, "hmac"), state}
	if _, err := s.key(identity); err != nil {
		return nil, err
	}
	return s, os.MkdirAll(state, 0700)
}
func validIdentity(id string) bool {
	return id != "" && id != "." && id != ".." && filepath.Base(id) == id
}
func (s *secureDatagrams) key(id string) ([]byte, error) {
	if !validIdentity(id) {
		return nil, errors.New("invalid identity")
	}
	k, err := os.ReadFile(filepath.Join(s.keys, id+".key"))
	if err != nil || len(k) != 32 {
		return nil, errors.New("missing or invalid HMAC key")
	}
	return k, nil
}

// lockCounter takes an exclusive lock across reading, checking and persisting the value.
func (s *secureDatagrams) counter(name string, proposed uint64, increment bool) (uint64, error) {
	lock, err := os.OpenFile(filepath.Join(s.state, name+".lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return 0, err
	}
	defer lock.Close()
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX); err != nil {
		return 0, err
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
	path := filepath.Join(s.state, name)
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return 0, err
	}
	var previous uint64
	if err == nil {
		previous, err = strconv.ParseUint(strings.TrimSpace(string(data)), 10, 63)
		if err != nil {
			return 0, fmt.Errorf("invalid persisted sequence: %w", err)
		}
	}
	if increment {
		proposed = previous + 1
	} else if proposed <= previous {
		return 0, errors.New("replay detected")
	}
	if proposed == 0 || proposed >= 1<<63 {
		return 0, errors.New("sequence exhausted")
	}
	tmp, err := os.CreateTemp(s.state, ".sequence-*")
	if err != nil {
		return 0, err
	}
	defer os.Remove(tmp.Name())
	if _, err = tmp.WriteString(strconv.FormatUint(proposed, 10)); err == nil {
		err = tmp.Sync()
	}
	if closeErr := tmp.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return 0, err
	}
	if err = os.Rename(tmp.Name(), path); err != nil {
		return 0, err
	}
	directory, err := os.Open(s.state)
	if err != nil {
		return 0, err
	}
	defer directory.Close()
	if err = directory.Sync(); err != nil {
		return 0, err
	}
	return proposed, nil
}
func encryptionCipher(key []byte) (cipher.AEAD, error) {
	derive := hmac.New(sha256.New, key)
	derive.Write([]byte("datamesh/udp/aes-gcm/v1"))
	block, err := aes.NewCipher(derive.Sum(nil))
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

func (s *secureDatagrams) encode(kind byte, payload []byte) ([]byte, error) {
	key, err := s.key(s.identity)
	if err != nil {
		return nil, err
	}
	seq, err := s.counter("out-"+s.identity, 0, true)
	if err != nil {
		return nil, err
	}
	name := []byte(s.identity)
	if len(name) > 255 {
		return nil, errors.New("identity too long")
	}
	aead, err := encryptionCipher(key)
	if err != nil {
		return nil, err
	}
	associated := make([]byte, 26+len(name))
	copy(associated, []byte("DMS2"))
	associated[4] = kind
	associated[5] = byte(len(name))
	binary.BigEndian.PutUint64(associated[6:14], seq)
	binary.BigEndian.PutUint64(associated[14:22], uint64(time.Now().UnixMilli()))
	binary.BigEndian.PutUint32(associated[22:26], uint32(len(payload)+aead.Overhead()))
	copy(associated[26:], name)
	nonce := make([]byte, aead.NonceSize())
	if _, err = rand.Read(nonce); err != nil {
		return nil, err
	}
	ciphertext := aead.Seal(nil, nonce, payload, associated)
	result := append(associated, nonce...)
	result = append(result, ciphertext...)
	mac := hmac.New(sha256.New, key)
	mac.Write(result)
	return append(result, mac.Sum(nil)...), nil
}

func (s *secureDatagrams) discovery(data []byte) ([]byte, error) {
	if len(data) < 86 || string(data[:4]) != "DMS2" || data[4] != 1 {
		return nil, errors.New("invalid discovery envelope")
	}
	n := int(data[5])
	size := int(binary.BigEndian.Uint32(data[22:26]))
	if n == 0 || size < 16 || len(data) != 26+n+12+size+32 || string(data[26:26+n]) != "gateway" {
		return nil, errors.New("invalid discovery sender or length")
	}
	key, err := s.key("gateway")
	if err != nil {
		return nil, err
	}
	mac := hmac.New(sha256.New, key)
	mac.Write(data[:len(data)-32])
	if !hmac.Equal(mac.Sum(nil), data[len(data)-32:]) {
		return nil, errors.New("discovery authentication failed")
	}
	delta := time.Now().UnixMilli() - int64(binary.BigEndian.Uint64(data[14:22]))
	if delta < -5000 || delta > 5000 {
		return nil, errors.New("discovery expired")
	}
	aead, err := encryptionCipher(key)
	if err != nil {
		return nil, err
	}
	headerEnd := 26 + n
	plaintext, err := aead.Open(nil, data[headerEnd:headerEnd+12], data[headerEnd+12:len(data)-32], data[:headerEnd])
	if err != nil {
		return nil, errors.New("discovery decryption failed")
	}
	seq := binary.BigEndian.Uint64(data[6:14])
	if _, err = s.counter("in-"+s.identity+"-gateway", seq, false); err != nil {
		return nil, fmt.Errorf("discovery: %w", err)
	}
	return plaintext, nil
}
