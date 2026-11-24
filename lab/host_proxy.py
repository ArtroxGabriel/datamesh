"""Expose only the two local lab web endpoints from Docker's internal network."""

import selectors
import socket
import socketserver
import threading
from typing import cast


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        destination = cast(Server, self.server).destination
        try:
            with socket.create_connection(destination, timeout=5) as upstream:
                self.request.settimeout(None)
                upstream.settimeout(None)
                with selectors.DefaultSelector() as selector:
                    selector.register(self.request, selectors.EVENT_READ, upstream)
                    selector.register(upstream, selectors.EVENT_READ, self.request)
                    while True:
                        for key, _ in selector.select(timeout=60):
                            data = cast(socket.socket, key.fileobj).recv(65536)
                            if not data:
                                return
                            key.data.sendall(data)
        except OSError:
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, destination: tuple[str, int]) -> None:
        self.destination = destination
        super().__init__(("127.0.0.1", port), Handler)


def main() -> None:
    console = Server(8081, ("172.30.53.15", 8081))
    threading.Thread(target=console.serve_forever, daemon=True).start()
    for port, dest in ((8080, ("172.30.53.13", 8080)), (8082, ("172.30.53.15", 8081))):
        try:
            proxy = Server(port, dest)
        except OSError as err:
            print(f"Proxy :{port} unavailable: {err}", flush=True)
        else:
            threading.Thread(target=proxy.serve_forever, daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
