"""Fixed-target attack runner, hosted in the Gateway network namespace."""

import json
import os
import socket
import sqlite3
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from scripts.attacks.lab_attack import capture, hijack_attempts, telemetry, transmit_replay


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database().close()
    threading.Thread(target=traffic_loop, daemon=True).start()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
lock = threading.Lock()
resume = threading.Event()
active: dict | None = None
stats: dict[str, int | str] = {"udp_packets": 0, "tcp_packets": 0, "bytes": 0}
DB = os.getenv("LAB_RUNS_DB", "/runs/runs.sqlite3")


class RunRequest(BaseModel):
    scenario: str
    automatic: bool = True
    mode: str


def database() -> sqlite3.Connection:
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    return db


def emit(message: str, source: str = "attacker", **extra: object) -> None:
    with lock:
        if active is not None:
            active["events"].append(
                {
                    "timestamp_ms": time.time_ns() // 1_000_000,
                    "source": source,
                    "message": message,
                    **extra,
                }
            )


def trigger() -> None:
    token = Path("/public/lab-control.token").read_text().strip()
    request = urllib.request.Request(
        "http://172.30.53.12:8092/anomaly", method="POST", headers={"X-Lab-Token": token}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("sensor anomaly request failed")
    emit("Anomalia térmica solicitada ao sensor", "system")


def find_packet() -> tuple[bytes, tuple]:
    for payload in capture(15, "eth0", "172.30.53.10"):
        reading = telemetry(payload)
        if reading and (reading[2] is None or (not reading[3] and reading[2] < 35)):
            return payload, reading
    raise TimeoutError("Nenhum pacote de sensor encontrado em 15 segundos")


def sample_run(run: dict, stop: threading.Event) -> None:
    while not stop.wait(1):
        try:
            with urllib.request.urlopen(
                "http://172.30.53.13:8080/api/security-events", timeout=2
            ) as response:
                security = json.load(response)
            with urllib.request.urlopen(
                "http://172.30.53.13:8080/api/telemetry/history?limit=50", timeout=2
            ) as response:
                history = json.load(response)
            with lock:
                run["samples"].append(
                    {
                        "timestamp_ms": time.time_ns() // 1_000_000,
                        "traffic": dict(stats),
                        "history": history,
                    }
                )
                run["security_events"] = [
                    event
                    for event in security["events"]
                    if event["timestamp_ms"] >= run["started_ms"]
                ]
        except (OSError, ValueError):
            continue


def run_scenario(run: dict) -> None:
    global active
    stop_samples = threading.Event()
    sampler = threading.Thread(target=sample_run, args=(run, stop_samples), daemon=True)
    sampler.start()
    try:
        scenario = run["scenario"]
        emit("Cenário iniciado")
        if scenario in ("sniff", "replay"):
            packet, reading = find_packet()
            sender, timestamp, temperature, _ = reading
            if temperature is None:
                emit(
                    f"Pacote cifrado de {sender}; temperatura indisponível",
                    ciphertext=packet[-48:-32].hex(),
                )
            else:
                emit(f"Pacote em claro de {sender}: {temperature:.1f} °C", temperature=temperature)
            if scenario == "replay":
                if not run["automatic"]:
                    with lock:
                        run["state"] = "waiting"
                    emit("Aguardando o apresentador acionar a anomalia e continuar")
                    if not resume.wait(60):
                        raise TimeoutError("Tempo para confirmação manual expirou")
                trigger()
                with lock:
                    run["state"] = "running"
                time.sleep(0.3)
                transmit_replay(packet, "172.30.53.10")
                emit("Enviadas 10 cópias; UDP não confirma aceitação", timestamp=timestamp)
                time.sleep(1)
                with urllib.request.urlopen(
                    "http://172.30.53.13:8080/api/telemetry/history?limit=100", timeout=3
                ) as response:
                    history = json.load(response)
                readings = [r for r in history if r["device_id"] == sender]
                if readings:
                    latest = max(readings, key=lambda r: r["timestamp_ms"])
                    emit(
                        f"Dashboard: {latest['temperature_c']:.1f} °C, alerta={latest['is_alert']}",
                        "system",
                    )
                    if timestamp is not None:
                        count = sum(r["timestamp_ms"] == timestamp for r in readings)
                        emit(f"Histórico: {count} registro(s) com o timestamp capturado", "system")
        else:
            emit("Tentando desligar o AC sem credenciais")
            for message, _ in hijack_attempts("172.30.53.11", Path("/public/ca.crt")):
                emit(message)
        with lock:
            run["state"] = "completed"
        emit("Cenário concluído", "system")
    except Exception as err:
        emit(f"Cenário interrompido: {err}", "system")
        with lock:
            run["state"] = "failed"
    finally:
        stop_samples.set()
        sampler.join(timeout=5)
        with lock:
            run["finished_ms"] = time.time_ns() // 1_000_000
            snapshot = json.dumps(run, ensure_ascii=False)
        with database() as db:
            db.execute("INSERT INTO runs (data) VALUES (?)", (snapshot,))
        with lock:
            active = None


def traffic_loop() -> None:
    try:
        with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as sock:
            sock.bind(("eth0", 0))
            while True:
                frame = sock.recv(65535)
                if len(frame) < 34 or frame[12:14] != b"\x08\x00":
                    continue
                protocol = frame[23]
                with lock:
                    stats["bytes"] = int(stats["bytes"]) + len(frame)
                    if protocol == 17:
                        stats["udp_packets"] = int(stats["udp_packets"]) + 1
                    elif protocol == 6:
                        stats["tcp_packets"] = int(stats["tcp_packets"]) + 1
    except OSError as err:
        with lock:
            stats["error"] = str(err)


@app.get("/status")
def status() -> dict:
    with lock:
        run = dict(active) if active else None
        if run is not None:
            run.pop("samples", None)
        return {"run": run, "traffic": dict(stats)}


@app.get("/runs")
def runs() -> list[dict]:
    with database() as db:
        rows = db.execute("SELECT id, data FROM runs ORDER BY id DESC LIMIT 100").fetchall()
    results = []
    for row in rows:
        run = json.loads(row[1])
        run["sample_count"] = len(run.get("samples", []))
        run.pop("samples", None)
        results.append(dict(run, id=row[0]))
    return results


@app.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    with database() as db:
        row = db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Execução não encontrada")
    return dict(json.loads(row[0]), id=run_id)


@app.post("/run")
def start_run(request: RunRequest) -> dict:
    global active
    if request.scenario not in {"sniff", "replay", "hijack"} or request.mode not in {
        "secure",
        "insecure",
    }:
        raise HTTPException(400, "Cenário ou modo inválido")
    with lock:
        if active is not None:
            raise HTTPException(409, "Já existe um cenário ativo")
        resume.clear()
        active = {
            "scenario": request.scenario,
            "automatic": request.automatic,
            "mode": request.mode,
            "state": "running",
            "events": [],
            "samples": [],
            "security_events": [],
            "started_ms": time.time_ns() // 1_000_000,
        }
        run = active
    threading.Thread(target=run_scenario, args=(run,), daemon=True).start()
    return {"started": True}


@app.post("/continue")
def continue_run() -> dict:
    with lock:
        if active is None or active["state"] != "waiting":
            raise HTTPException(409, "Nenhum replay aguardando confirmação")
        resume.set()
    return {"continued": True}
