#!/usr/bin/env bash
set -euo pipefail

mkdir -p gen/python gen/go
touch gen/__init__.py gen/python/__init__.py

# Generate Python protobuf, type stubs (.pyi), and gRPC stubs
uv run python -m grpc_tools.protoc \
  -Iproto \
  --python_out=gen/python \
  --pyi_out=gen/python \
  --grpc_python_out=gen/python \
  proto/datamesh.proto

# Generate Go protobuf structs (for PDU telemetry & discovery)
protoc \
  -Iproto \
  --go_out=gen/go \
  --go_opt=paths=source_relative \
  proto/datamesh.proto

cat > gen/go/go.mod << 'EOF'
module datamesh/gen/go

go 1.23

require google.golang.org/protobuf v1.36.5
EOF
