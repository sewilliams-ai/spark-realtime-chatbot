"""WHOOP OAuth and cache refresh client.

This module keeps the live WHOOP path outside the request hot path. The
interactive OAuth routes store tokens in demo_files/whoop_auth.json, and the
refresh command writes normalized WHOOP signals into demo_files/health.yaml.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import aiohttp
import yaml

from .http_session import get_http_manager


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
DEFAULT_API_BASE_URL = "https://api.prod.whoop.com/developer"
DEFAULT_REDIRECT_URI = "https://localhost:8443/whoop/callback"
DEFAULT_SCOPES = (
    "read:recovery",
    "read:sleep",
    "read:cycles",
    "read:workout",
    "offline",
)
HEALTH_YAML_HEADER = """# DUMMY DATA FOR DEMO/TESTING ONLY.
# The committed values are fake local health context for the Beat 3 demo.
# A local WHOOP refresh may replace only the `whoop:` subtree with real data.
# Do not commit refreshed WHOOP values or demo_files/whoop_auth.json.

"""


@dataclass(frozen=True)
class WhoopConfig:
    client_id: str | None = os.environ.get("WHOOP_CLIENT_ID")
    client_secret: str | None = os.environ.get("WHOOP_CLIENT_SECRET")
    redirect_uri: str = (
        os.environ.get("WHOOP_REDIRECT_URI")
        or os.environ.get("WHOOP_CALLBACK_URL")
        or DEFAULT_REDIRECT_URI
    )
    api_base_url: str = os.environ.get("WHOOP_API_BASE_URL", DEFAULT_API_BASE_URL)
    scopes: tuple[str, ...] = DEFAULT_SCOPES

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)


def health_yaml_path() -> Path:
    return Path(os.environ.get("HEALTH_YAML_PATH", str(REPO_ROOT / "demo_files" / "health.yaml")))


def auth_tokens_path() -> Path:
    return Path(os.environ.get("WHOOP_AUTH_PATH", str(REPO_ROOT / "demo_files" / "whoop_auth.json")))


def auth_url(state: str, cfg: WhoopConfig | None = None) -> str:
    cfg = cfg or WhoopConfig()
    if not cfg.client_id:
        raise RuntimeError("WHOOP_CLIENT_ID is required")
    params = {
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg.scopes),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def _token_request(payload: dict[str, str], cfg: WhoopConfig | None = None) -> dict[str, Any]:
    cfg = cfg or WhoopConfig()
    if not cfg.enabled:
        raise RuntimeError("WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET are required")

    full_payload = {
        **payload,
        "client_id": cfg.client_id or "",
        "client_secret": cfg.client_secret or "",
    }
    if payload.get("grant_type") == "authorization_code":
        full_payload["redirect_uri"] = cfg.redirect_uri
    if payload.get("grant_type") == "refresh_token":
        full_payload["scope"] = "offline"
    session = await get_http_manager().get_session()
    async with session.post(TOKEN_URL, data=full_payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        body = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"WHOOP token request failed with HTTP {resp.status}: {body[:300]}")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("WHOOP token response was not JSON") from exc


async def exchange_code(code: str, cfg: WhoopConfig | None = None) -> dict[str, Any]:
    return await _token_request({"grant_type": "authorization_code", "code": code}, cfg)


async def refresh_token(refresh_token: str, cfg: WhoopConfig | None = None) -> dict[str, Any]:
    return await _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, cfg)


def write_auth_tokens(tokens: dict[str, Any], path: Path | None = None) -> Path:
    path = path or auth_tokens_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    return path


def load_auth_tokens(path: Path | None = None) -> dict[str, Any]:
    path = path or auth_tokens_path()
    return json.loads(path.read_text(encoding="utf-8"))


async def _api_get(path: str, access_token: str, cfg: WhoopConfig) -> dict[str, Any]:
    url = cfg.api_base_url.rstrip("/") + path
    session = await get_http_manager().get_session()
    headers = {"Authorization": f"Bearer {access_token}"}
    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        body = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"WHOOP API GET {path} failed with HTTP {resp.status}: {body[:300]}")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"WHOOP API GET {path} returned non-JSON") from exc


def _first_record(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records")
    if isinstance(records, list) and records:
        first = records[0]
        return first if isinstance(first, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _score(record: dict[str, Any]) -> dict[str, Any]:
    score = record.get("score")
    return score if isinstance(score, dict) else {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_whoop_payloads(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fetched_at = _now_iso()
    recovery_score = _score(_first_record(payloads.get("recovery") or {}))
    sleep_score = _score(_first_record(payloads.get("sleep") or {}))
    cycle_score = _score(_first_record(payloads.get("cycle") or {}))

    workouts = []
    workout_records = (payloads.get("workout") or {}).get("records") or []
    for record in workout_records[:3]:
        if not isinstance(record, dict):
            continue
        score = _score(record)
        workouts.append({
            "sport": record.get("sport_name") or record.get("sport_id") or "Workout",
            "strain": score.get("strain"),
            "kilojoule": score.get("kilojoule"),
            "average_heart_rate": score.get("average_heart_rate"),
            "started_at": record.get("start"),
            "fetched_at": fetched_at,
        })

    return {
        "recovery": {
            "recovery_score": recovery_score.get("recovery_score"),
            "resting_heart_rate": recovery_score.get("resting_heart_rate"),
            "hrv_rmssd_milli": recovery_score.get("hrv_rmssd_milli"),
            "spo2_percentage": recovery_score.get("spo2_percentage"),
            "fetched_at": fetched_at,
        },
        "sleep": {
            "sleep_performance_percentage": sleep_score.get("sleep_performance_percentage"),
            "total_in_bed_time_milli": sleep_score.get("total_in_bed_time_milli"),
            "total_rem_sleep_time_milli": sleep_score.get("total_rem_sleep_time_milli"),
            "total_slow_wave_sleep_time_milli": sleep_score.get("total_slow_wave_sleep_time_milli"),
            "fetched_at": fetched_at,
        },
        "cycle": {
            "strain": cycle_score.get("strain"),
            "kilojoule": cycle_score.get("kilojoule"),
            "average_heart_rate": cycle_score.get("average_heart_rate"),
            "fetched_at": fetched_at,
        },
        "recent_workouts": workouts,
    }


async def fetch_all(access_token: str | None = None, cfg: WhoopConfig | None = None) -> dict[str, Any]:
    cfg = cfg or WhoopConfig()
    if not access_token:
        tokens = load_auth_tokens()
        access_token = tokens.get("access_token")
    if not access_token:
        raise RuntimeError("WHOOP access token is required")

    payloads = {
        "recovery": await _api_get("/v2/recovery?limit=1", access_token, cfg),
        "sleep": await _api_get("/v2/activity/sleep?limit=1", access_token, cfg),
        "cycle": await _api_get("/v2/cycle?limit=1", access_token, cfg),
        "workout": await _api_get("/v2/activity/workout?limit=3", access_token, cfg),
    }
    return normalize_whoop_payloads(payloads)


def write_to_health_yaml(whoop_data: dict[str, Any], path: Path | None = None) -> Path:
    path = path or health_yaml_path()
    data: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    data["whoop"] = whoop_data

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    tmp_path.write_text(HEALTH_YAML_HEADER + body, encoding="utf-8")
    tmp_path.replace(path)
    return path


async def refresh_cache(cfg: WhoopConfig | None = None) -> dict[str, Any]:
    cfg = cfg or WhoopConfig()
    tokens = load_auth_tokens()
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("No WHOOP refresh token found; visit /whoop/login first")
    new_tokens = await refresh_token(refresh, cfg)
    write_auth_tokens(new_tokens)
    whoop_data = await fetch_all(new_tokens.get("access_token"), cfg)
    write_to_health_yaml(whoop_data)
    return whoop_data


def main() -> int:
    parser = argparse.ArgumentParser(description="WHOOP OAuth/cache helper")
    parser.add_argument("--refresh", action="store_true", help="Refresh tokens and update demo_files/health.yaml")
    parser.add_argument("--auth-url", action="store_true", help="Print a login URL for manual OAuth testing")
    args = parser.parse_args()

    if args.auth_url:
        print(auth_url("manual01"))
        return 0
    if args.refresh:
        asyncio.run(refresh_cache())
        print(f"WHOOP cache refreshed: {health_yaml_path()}")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
