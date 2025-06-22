#!/usr/bin/env python3
"""
Product Research Tool – v2.4
===========================
Improved fallback for Streamlit Cloud to avoid showing CLI-only keyword errors.

Changelog:
----------
* Ensures `streamlit_app()` is always called if run from Streamlit (i.e., as `streamlit run ...`).
* Prevents CLI fallback block (`--keyword required`) from triggering in Streamlit context.
"""

from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import os
import re
import smtplib
import sys
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from pytrends.request import TrendReq
from rich.console import Console

# Optional; only imported when Streamlit mode is active
try:
    import streamlit as st
    import altair as alt
except ImportError:
    st = None
    alt = None

console = Console()
DATA_DIR = Path("reports")

# Placeholder for full method bodies from original script (omitted for brevity)

def streamlit_app():
    st.set_page_config(page_title="Product Research Tool", layout="wide")
    st.title("🛠️ Product Research Tool")
    keyword = st.text_input("Keyword", "yoga mat")
    amazon_url = st.text_input(
        "Amazon Best‑Sellers URL",
        "https://www.amazon.com/Best-Sellers-Sports-Outdoors/zgbs/sporting-goods",
    )
    cols = st.columns(3)
    with cols[0]:
        google_chk = st.checkbox("Google Trends", True)
        amazon_chk = st.checkbox("Amazon", True)
    with cols[1]:
        ebay_chk = st.checkbox("eBay", True)
        ali_chk = st.checkbox("AliExpress", True)
    with cols[2]:
        tiktok_chk = st.checkbox("TikTok", False)
    run_btn = st.button("Run Research")

    if run_btn:
        sources: List[str] = []
        if google_chk: sources.append("google")
        if amazon_chk: sources.append("amazon")
        if ebay_chk: sources.append("ebay")
        if ali_chk: sources.append("aliexpress")
        if tiktok_chk: sources.append("tiktok")
        run_research(keyword, amazon_url, sources)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", type=str)
    parser.add_argument("--amazon", type=str)
    parser.add_argument("--sources", nargs="+", default=["google", "amazon"])
    parser.add_argument("--schedule", type=str)
    parser.add_argument("--email_to", type=str)
    parser.add_argument("--smtp_json", type=str)
    parser.add_argument("--streamlit", action="store_true")
    args = parser.parse_args()

    if "streamlit" in sys.argv[0] or args.streamlit or (st and not any(vars(args).values())):
        streamlit_app()
    elif args.keyword:
        run_research(args.keyword, args.amazon, args.sources)
    elif args.schedule and args.email_to and args.smtp_json:
        smtp_cfg = json.loads(Path(args.smtp_json).read_text())
        schedule_jobs([args.keyword], args.amazon, args.sources, args.schedule, args.email_to, smtp_cfg)
    else:
        console.print("[red]At least one --keyword is required (unless running via Streamlit)")
        sys.exit(1)
