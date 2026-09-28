"""Opt-in live ERP check; normal tests must never depend on NIST availability."""

import os

import pytest

from app.config import Config
from app.nist_client import NistClient
from app.schedule_monitor import today_in_kolkata
from app.schedule_parser import parse_schedule


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_NIST_INTEGRATION") != "1", reason="Set RUN_NIST_INTEGRATION=1 to call NIST.")
def test_live_nist_endpoint_returns_a_parseable_or_explicit_empty_page(tmp_path):
    config = Config.from_env()
    html = NistClient(tmp_path, save_raw_html=True).fetch(today_in_kolkata(), "08:15 AM")
    assert "No Schedule Found for the selected date and time" in html or parse_schedule(html) is not None
