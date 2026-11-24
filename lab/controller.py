"""Local presenter console and tightly scoped Compose controller."""

import asyncio
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
ATTACKER = "http://172.30.53.10:8091"
CLIENT = "http://172.30.53.13:8080"
PROJECT = "datamesh-security-lab"
ROOT = os.environ.get("LAB_REPO_ROOT", "/workspace")
switch_lock = threading.Lock()
switching = False
switch_error = ""


class ModeRequest(BaseModel):
    mode: str


class ScenarioRequest(BaseModel):
    scenario: str
    automatic: bool = True


class ActionRequest(BaseModel):
    action: str
    target: str = ""
    source_type: str = ""
    param: str = ""


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")
_EXTRA_PREFIX = "datamesh-extra-"
_CORE_SERVICES = ("gateway", "client", "temperature", "pdu", "ac", "attacker")
_BASE_SERVICE_BY_ID = {
    "temperature": "temperature",
    "temp-01-turing": "temperature",
    "pdu": "pdu",
    "pdu-01-tesla": "pdu",
    "ac": "ac",
    "ac-01-carnot": "ac",
}
_ALLOWED_ORIGINS = {
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:8082",
    "http://127.0.0.1:8082",
}


@app.middleware("http")
async def local_host_only(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    origin = request.headers.get("origin", "")
    if host not in {"localhost", "127.0.0.1"} or (origin and origin not in _ALLOWED_ORIGINS):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "local access only"}, status_code=403)
    return await call_next(request)


def fetch(url: str, data: dict | None = None) -> dict | list:
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def snapshot() -> dict:
    result: dict = {
        "switching": switching,
        "switch_error": switch_error,
        "ready": False,
        "extras": extra_containers(),
    }
    try:
        result["security"] = fetch(CLIENT + "/api/security-events")
        result["devices"] = fetch(CLIENT + "/api/devices")
        result["history"] = fetch(CLIENT + "/api/telemetry/history?limit=100")
        result["attacker"] = fetch(ATTACKER + "/status")
        result["runs"] = fetch(ATTACKER + "/runs")
        result["ready"] = not switching
    except (OSError, ValueError):
        result["error"] = "Aguardando Gateway, cliente e atacante"
    return result


def switch_stack(mode: str) -> None:
    global switching, switch_error
    try:
        env = dict(os.environ, DATAMESH_SECURITY_MODE=mode, PWD=ROOT)
        command = [
            "docker",
            "compose",
            "-p",
            PROJECT,
            "-f",
            "compose.lab.yml",
            "--profile",
            "attack",
            "up",
            "-d",
            "--no-build",
            "--force-recreate",
            "gateway",
            "client",
            "temperature",
            "pdu",
            "ac",
            "attacker",
        ]
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-1500:])
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                security = fetch(CLIENT + "/api/security-events")
                devices = fetch(CLIENT + "/api/devices")
                fetch(ATTACKER + "/status")
                if (
                    isinstance(security, dict)
                    and security.get("mode") == mode
                    and isinstance(devices, list)
                    and len(devices) >= 3
                ):
                    return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise TimeoutError("Os serviços não ficaram prontos no modo solicitado")
    except Exception as err:
        switch_error = str(err)
    finally:
        with switch_lock:
            switching = False


def docker_run(*args: str, env: dict[str, str] | None = None, timeout: int = 30) -> str:
    result = subprocess.run(
        ["docker", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:] or f"docker failed: {args[0]}")
    return result.stdout


def compose_run(*args: str, env: dict[str, str] | None = None, timeout: int = 30) -> str:
    return docker_run(
        "compose",
        "-p",
        PROJECT,
        "-f",
        "compose.lab.yml",
        "--profile",
        "attack",
        *args,
        env=env,
        timeout=timeout,
    )


def extra_containers() -> list[str]:
    try:
        out = docker_run("ps", "-a", "--filter", f"name={_EXTRA_PREFIX}", "--format", "{{.Names}}")
        return [name.removeprefix(_EXTRA_PREFIX) for name in out.splitlines() if name.strip()]
    except (OSError, RuntimeError):
        return []


def _resolve_target(target: str) -> tuple[bool, str]:
    if target in _BASE_SERVICE_BY_ID:
        return True, _BASE_SERVICE_BY_ID[target]
    if _ID_RE.fullmatch(target) and target not in {"gateway", "client", "attacker"}:
        return False, f"{_EXTRA_PREFIX}{target}"
    raise HTTPException(400, "Fonte inválida")


_SCIENTISTS = ("curie", "faraday", "maxwell", "lovelace", "shannon", "hopper", "dijkstra")


def _next_device_id(source_type: str) -> str:
    prefix = "temp" if source_type == "temp" else "pdu"
    existing = set(extra_containers())
    for idx in range(2, 100):
        name = _SCIENTISTS[(idx - 2) % len(_SCIENTISTS)]
        candidate = f"{prefix}-{idx:02d}-{name}"
        if candidate not in existing:
            return candidate
    raise HTTPException(409, "Limite de fontes extras atingido")


def _add_source(source_type: str, device_id: str, param: str) -> str:
    if source_type not in {"temp", "pdu"}:
        raise HTTPException(400, "Tipo inválido")
    if not device_id:
        device_id = _next_device_id(source_type)
    elif not _ID_RE.fullmatch(device_id):
        raise HTTPException(400, "device_id inválido")
    mode = snapshot().get("security", {}).get("mode", "insecure")
    if mode == "secure":
        docker_run(
            "run",
            "--rm",
            "-e",
            "DATAMESH_CREDENTIALS_DIR=/security",
            "-v",
            f"{ROOT}/.datamesh-security:/security",
            f"{PROJECT}-temperature",
            "python",
            "scripts/security/generate_hmac_keys.py",
            device_id,
        )
    image = f"{PROJECT}-temperature" if source_type == "temp" else f"{PROJECT}-pdu"
    cmd = ["python", "-m", "sources.temperature.main"] if source_type == "temp" else ["pdu"]
    env_args = [
        "-e",
        f"DATAMESH_SECURITY_MODE={mode}",
        "-e",
        "DATAMESH_CREDENTIALS_DIR=/security",
        "-e",
        "DATAMESH_SECURITY_STATE_DIR=/state",
        "-e",
        "SEND_INTERVAL_SEC=2",
    ]
    if source_type == "temp":
        env_args += ["-e", f"SENSOR_ID={device_id}", "-e", f"BASE_TEMP_C={param or '24.5'}"]
    else:
        env_args += [
            "-e",
            f"PDU_DEVICE_ID={device_id}",
            "-e",
            f"BASE_POWER_WATTS={param or '1600'}",
        ]
    vol_args = (
        [
            "-v",
            f"{ROOT}/.datamesh-security/hmac/gateway.key:/security/hmac/gateway.key:ro",
            "-v",
            f"{ROOT}/.datamesh-security/hmac/{device_id}.key:/security/hmac/{device_id}.key:ro",
        ]
        if mode == "secure"
        else []
    )
    docker_run(
        "run",
        "-d",
        "--name",
        f"{_EXTRA_PREFIX}{device_id}",
        "--network",
        f"{PROJECT}_lab",
        "--cap-add",
        "NET_ADMIN",
        *env_args,
        *vol_args,
        image,
        *cmd,
        timeout=60,
    )
    return device_id


@app.get("/")
def page(request: Request) -> FileResponse:
    host = request.headers.get("host", "")
    name = "menu.html" if host.endswith(":8082") else "console.html"
    return FileResponse(Path(__file__).with_name(name))


@app.get("/menu")
def menu_page() -> FileResponse:
    return FileResponse(Path(__file__).with_name("menu.html"))


@app.get("/api/state")
def state() -> dict:
    return snapshot()


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def events():
        while True:
            state = await asyncio.to_thread(snapshot)
            yield "data: " + json.dumps(state, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.post("/api/mode")
def change_mode(request: ModeRequest) -> dict:
    global switching, switch_error
    if request.mode not in {"secure", "insecure"}:
        raise HTTPException(400, "Modo inválido")
    with switch_lock:
        if switching:
            raise HTTPException(409, "Troca em andamento")
        state = snapshot()
        if not state.get("ready"):
            raise HTTPException(503, "Laboratório indisponível")
        if state.get("attacker", {}).get("run"):
            raise HTTPException(409, "Aguarde a conclusão do cenário")
        switching = True
        switch_error = ""
    threading.Thread(target=switch_stack, args=(request.mode,), daemon=True).start()
    return {"switching": True}


@app.post("/api/run")
def start_run(request: ScenarioRequest) -> dict:
    if request.scenario not in {"sniff", "replay", "hijack"}:
        raise HTTPException(400, "Cenário inválido")
    state = snapshot()
    if not state.get("ready"):
        raise HTTPException(503, "Laboratório indisponível")
    try:
        result = fetch(
            ATTACKER + "/run",
            {
                "scenario": request.scenario,
                "automatic": request.automatic,
                "mode": state["security"]["mode"],
            },
        )
    except urllib.error.HTTPError as err:
        raise HTTPException(err.code, "Cenário indisponível") from err
    if not isinstance(result, dict):
        raise HTTPException(502, "Resposta inválida")
    return result


@app.post("/api/continue")
def continue_run() -> dict:
    try:
        result = fetch(ATTACKER + "/continue", {})
    except urllib.error.HTTPError as err:
        raise HTTPException(err.code, "Nenhum replay aguardando confirmação") from err
    if not isinstance(result, dict):
        raise HTTPException(502, "Resposta inválida")
    return result


@app.post("/api/action")
def run_action(request: ActionRequest) -> dict:
    target = request.target
    if request.action == "stack_up":
        compose_run("up", "-d", "--no-build", *_CORE_SERVICES, timeout=120)
    elif request.action == "stack_down":
        for extra in extra_containers():
            docker_run("rm", "-f", f"{_EXTRA_PREFIX}{extra}")
        compose_run("stop", *_CORE_SERVICES, timeout=60)
    elif request.action == "temp_anomaly":
        compose_run("kill", "-s", "USR1", "temperature")
    elif request.action == "pdu_overload":
        compose_run("kill", "-s", "USR1", "pdu")
    elif request.action in {"anomaly", "stop_source", "start_source"}:
        is_base, name = _resolve_target(request.target)
        if request.action == "anomaly":
            if name == "ac":
                raise HTTPException(400, "AC não possui gatilho de anomalia")
            args = ("kill", "-s", "USR1", name)
        else:
            args = ("stop" if request.action == "stop_source" else "start", name)
        compose_run(*args) if is_base else docker_run(*args)
    elif request.action == "add_source":
        target = _add_source(request.source_type, request.target, request.param)
    elif request.action == "remove_source":
        if not _ID_RE.fullmatch(request.target):
            raise HTTPException(400, "device_id inválido")
        docker_run("rm", "-f", f"{_EXTRA_PREFIX}{request.target}")
    else:
        raise HTTPException(400, "Ação inválida")
    return {"ok": True, "action": request.action, "target": target}
