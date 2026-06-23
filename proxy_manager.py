#!/usr/bin/env python3
"""
proxy_manager.py
Parses a VLESS URL from the VLESS_LINK environment variable,
generates an xray-core config.json, and launches xray as a
local SOCKS5 proxy on 127.0.0.1:1080.
"""
import os
import sys
import json
import subprocess
import urllib.parse


XRAY_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xray', 'xray')
XRAY_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xray_config.json')


def parse_vless(link: str) -> dict:
    """Parse a vless:// URL and return its components as a dict."""
    # vless://UUID@host:port?params#name
    link = link.strip()
    if not link.startswith("vless://"):
        raise ValueError("VLESS_LINK must start with vless://")

    without_scheme = link[len("vless://"):]
    # Split off fragment (the name after #)
    if "#" in without_scheme:
        without_scheme, _ = without_scheme.rsplit("#", 1)

    # Split UUID from the rest
    at_idx = without_scheme.index("@")
    uuid = without_scheme[:at_idx]
    rest = without_scheme[at_idx + 1:]

    # Split host:port from query params
    if "?" in rest:
        host_port, query = rest.split("?", 1)
    else:
        host_port, query = rest, ""

    # Remove any trailing slashes from host_port
    host_port = host_port.rstrip("/")


    # Handle IPv6
    if host_port.startswith("["):
        bracket_end = host_port.index("]")
        host = host_port[1:bracket_end]
        port = int(host_port[bracket_end + 2:])
    else:
        parts = host_port.rsplit(":", 1)
        host = parts[0]
        port = int(parts[1])

    params = dict(urllib.parse.parse_qsl(query))

    return {
        "uuid": uuid,
        "host": host,
        "port": port,
        "security": params.get("security", "none"),
        "type": params.get("type", "tcp"),
        "path": params.get("path", "/"),
        "sni": params.get("sni", host),
        "ws_host": params.get("host", host),
        "encryption": params.get("encryption", "none"),
    }


def build_xray_config(v: dict) -> dict:
    """Build a minimal xray config.json for a VLESS+WS+TLS outbound."""
    stream_settings = {
        "network": v["type"],
        "security": v["security"],
    }

    if v["type"] == "ws":
        stream_settings["wsSettings"] = {
            "path": v["path"],
            "headers": {
                "Host": v["ws_host"]
            }
        }

    if v["security"] == "tls":
        stream_settings["tlsSettings"] = {
            "serverName": v["sni"],
            "allowInsecure": True
        }

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 1080,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {
                    "auth": "noauth",
                    "udp": True
                }
            },
            {
                "port": 8118,
                "listen": "127.0.0.1",
                "protocol": "http",
                "settings": {}
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": v["host"],
                            "port": v["port"],
                            "users": [
                                {
                                    "id": v["uuid"],
                                    "encryption": v["encryption"],
                                    "flow": ""
                                }
                            ]
                        }
                    ]
                },
                "streamSettings": stream_settings
            },
            {
                "protocol": "freedom",
                "tag": "direct"
            }
        ]
    }
    return config


def start_xray() -> subprocess.Popen | None:
    """Start xray if VLESS_LINK is set in environment. Returns the process or None."""
    link = os.environ.get("VLESS_LINK", "").strip()
    if not link:
        print("[Proxy] No VLESS_LINK found in environment. Running without proxy.")
        return None

    if not os.path.isfile(XRAY_BIN):
        print(f"[Proxy] xray binary not found at {XRAY_BIN}. Running without proxy.")
        return None

    try:
        v = parse_vless(link)
    except Exception as e:
        print(f"[Proxy] Failed to parse VLESS_LINK: {e}. Running without proxy.")
        return None

    config = build_xray_config(v)
    with open(XRAY_CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print(f"[Proxy] Starting xray → VLESS {v['host']}:{v['port']} via {v['type'].upper()}")
    proc = subprocess.Popen(
        [XRAY_BIN, "run", "-c", XRAY_CONFIG],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE
    )
    # Give it a moment to start
    import time
    time.sleep(2)
    if proc.poll() is not None:
        err = proc.stderr.read().decode(errors="replace")
        print(f"[Proxy] xray failed to start: {err}")
        return None

    print("[Proxy] xray running! SOCKS5 proxy at 127.0.0.1:1080 | HTTP at 127.0.0.1:8118")
    return proc


if __name__ == "__main__":
    proc = start_xray()
    if proc:
        proc.wait()
