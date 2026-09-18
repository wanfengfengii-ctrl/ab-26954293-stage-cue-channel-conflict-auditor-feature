import os
import time

import pytest
import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000")
WEB_URL = os.environ.get("WEB_URL", "http://localhost:8080")


@pytest.fixture(scope="session", autouse=True)
def wait_for_services() -> None:
    """等待 web 与 api 就绪；超时则整个验收失败。"""
    deadline = time.monotonic() + 60
    pending = {"api": f"{API_URL}/healthz", "web": WEB_URL}
    while pending and time.monotonic() < deadline:
        for name, url in list(pending.items()):
            try:
                if requests.get(url, timeout=2).status_code == 200:
                    del pending[name]
            except requests.RequestException:
                pass
        if pending:
            time.sleep(1)
    if pending:
        pytest.fail(f"服务未就绪: {', '.join(pending)}")


@pytest.fixture(scope="session")
def api_url() -> str:
    return API_URL


@pytest.fixture(scope="session")
def web_url() -> str:
    return WEB_URL
