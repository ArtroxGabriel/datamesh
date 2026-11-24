#!/usr/bin/env bash
set -euo pipefail
umask 077
out="${DATAMESH_CREDENTIALS_DIR:-.datamesh-security}"
if [[ -e "$out" ]]; then
    echo "Credential directory already exists: $out (remove it explicitly to rotate)" >&2
    exit 1
fi
mkdir -p "$out"
openssl req -x509 -newkey rsa:3072 -nodes -days 7 -subj '/CN=DataMesh Demo CA' \
    -keyout "$out/ca.key" -out "$out/ca.crt" >/dev/null 2>&1
for identity in gateway ac client; do
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$identity" \
        -keyout "$out/$identity.key" -out "$out/$identity.csr" >/dev/null 2>&1
    printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth,clientAuth\n' "$identity" > "$out/$identity.ext"
    openssl x509 -req -in "$out/$identity.csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" \
        -CAcreateserial -days 7 -extfile "$out/$identity.ext" -out "$out/$identity.crt" >/dev/null 2>&1
    rm "$out/$identity.csr" "$out/$identity.ext"
done
printf 'Demo credentials created in %s (valid for seven days).\n' "$out"
