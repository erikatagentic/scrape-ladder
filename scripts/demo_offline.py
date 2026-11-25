"""The offline demo without Docker.

Serves fixtures/site and the API on loopback, maps the name fixture.test to the fixture
server, then waits. In another terminal, run the curl it prints. Ctrl-C stops both.

    python scripts/demo_offline.py
"""
from __future__ import annotations

import functools
import os
import sys
import threading
import time
from dataclasses import dataclass, replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from scrape_ladder.api import create_app  # noqa: E402
from scrape_ladder.guard import system_resolver  # noqa: E402
from scrape_ladder.settings import Settings  # noqa: E402

SITE = ROOT / "fixtures" / "site"
FIXTURE_HOST = "fixture.test"
LOOPBACK = "127.0.0.1"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the demo output to the curl result
        pass


@dataclass
class Demo:
    api_port: int
    fixture_port: int
    _fixture: ThreadingHTTPServer
    _api: uvicorn.Server
    _threads: list[threading.Thread]

    @property
    def article_url(self) -> str:
        return f"http://{FIXTURE_HOST}:{self.fixture_port}/article.html"

    @property
    def api_url(self) -> str:
        return f"http://{LOOPBACK}:{self.api_port}"

    def stop(self) -> None:
        self._api.should_exit = True
        self._fixture.shutdown()
        for thread in self._threads:
            thread.join(timeout=5)
        self._fixture.server_close()


def _resolver(host: str) -> list[str]:
    return [LOOPBACK] if host == FIXTURE_HOST else system_resolver(host)


def start(api_port: int = 8080, fixture_port: int = 8081, settings: Settings | None = None) -> Demo:
    handler = functools.partial(_QuietHandler, directory=str(SITE))
    fixture = ThreadingHTTPServer((LOOPBACK, fixture_port), handler)
    fixture_port = fixture.server_address[1]

    settings = replace(settings or Settings.from_env(), trusted_hosts=frozenset({FIXTURE_HOST}))
    app = create_app(settings, resolver=_resolver)
    server = uvicorn.Server(uvicorn.Config(app, host=LOOPBACK, port=api_port, log_level="warning"))

    threads = [
        threading.Thread(target=fixture.serve_forever, daemon=True),
        threading.Thread(target=server.run, daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline or not threads[1].is_alive():
            fixture.shutdown()
            raise RuntimeError("the API didn't start")
        time.sleep(0.05)
    if api_port == 0:
        api_port = server.servers[0].sockets[0].getsockname()[1]
    return Demo(api_port, fixture_port, fixture, server, threads)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    demo = start(int(os.environ.get("PORT", "8080")))
    body = '{"url":"' + demo.article_url + '"}'
    print("API and fixture site are up. In another terminal run:\n")
    print(f"  curl -s -X POST localhost:{demo.api_port}/scrape-url \\")
    print("    -H 'content-type: application/json' \\")
    print(f"    -d '{body}'\n")
    print("Ctrl-C stops both.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        demo.stop()


if __name__ == "__main__":
    main()
