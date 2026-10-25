"""Executable entrypoint for DataMesh DCIM FastAPI Web Client."""

import logging
import os

import uvicorn

from client.app import create_app
from client.events import EventTimeline, TimelinePoller
from client.gateway_client import TCPGatewayClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("web-client")


def _load_config() -> tuple[str, int, str, int]:
    web_host = os.getenv("WEB_HOST", "0.0.0.0")
    web_port = int(os.getenv("WEB_PORT", "8080"))
    gateway_host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    gateway_port = int(os.getenv("GATEWAY_PORT") or os.getenv("GATEWAY_TCP_PORT", "9997"))
    return web_host, web_port, gateway_host, gateway_port


def main() -> None:
    web_host, web_port, gw_host, gw_port = _load_config()
    logger.info("Connecting to DataMesh Gateway at TCP %s:%d", gw_host, gw_port)
    client = TCPGatewayClient(host=gw_host, port=gw_port)
    timeline = EventTimeline()
    # Started here rather than in create_app so tests can build the app without a polling thread.
    TimelinePoller(client, timeline).start()
    app = create_app(gateway_client=client, timeline=timeline)

    logger.info("Starting Web Dashboard on http://%s:%d", web_host, web_port)
    uvicorn.run(app, host=web_host, port=web_port)


if __name__ == "__main__":
    main()
