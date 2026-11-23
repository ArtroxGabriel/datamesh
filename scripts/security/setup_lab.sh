#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ ! -d .datamesh-security ]]; then
    scripts/security/generate_credentials.sh
fi
python scripts/security/generate_hmac_keys.py \
    ac-01-carnot temp-01-turing temp-02-curie pdu-01-tesla pdu-02-faraday

if [[ ! -f .datamesh-security/lab-control.token ]]; then
    umask 077
    openssl rand -hex 32 > .datamesh-security/lab-control.token
fi
