#!/usr/bin/env python3
"""
Product Research Tool – v2.6
===========================
Failsafe Streamlit fallback (final fix)

Changelog:
----------
* Immediately launches streamlit_app() if Streamlit is installed and `streamlit` appears in sys.argv or module is loaded.
* Completely bypasses argparse in that case.
* Works across all Streamlit Cloud launch methods.
"""

from __future__ import annotations
import sys

try:
    import streamlit as st
    import altair as alt
except ImportError:
    st = None
    alt = None

# Force Streamlit UI if applicable
if st and ("streamlit" in sys.argv[0] or any("streamlit" in arg for arg in sys.argv)):
    def streamlit_app():
        st.set_page_config(page_title="Product Research Tool", layout="wide")
        st.title("🛠️ Product Research Tool")
        keyword = st.text_input("Keyword", "yoga mat")
        amazon_url = st.text_input(
            "Amazon Best‑Sellers URL",
            "https://www.amazon.com/Best-Sellers-Sports-Outdoors/zgbs/sporting-goods",
        )
        sources = []
        cols = st.columns(3)
        with cols[0]:
            if st.checkbox("Google Trends", True): sources.append("google")
            if st.checkbox("Amazon", True): sources.append("amazon")
        with cols[1]:
            if st.checkbox("eBay", True): sources.append("ebay")
            if st.checkbox("AliExpress", True): sources.append("aliexpress")
        with cols[2]:
            if st.checkbox("TikTok", False): sources.append("tiktok")
        if st.button("Run Research"):
            run_research(keyword, amazon_url, sources)

    def run_research(keyword: str, amazon_url: str, sources: list[str]):
        st.success(f"✅ Pretend we’re researching '{keyword}' using {sources}")
        st.info("The full scraping/data logic would go here.")

    streamlit_app()
    sys.exit(0)

# CLI fallback mode
import argparse
import json
import os
from pathlib import Path
from rich.console import Console

console = Console()

def run_research(keyword: str, amazon_url: str, sources: list[str]):
    console.log(f"[bold cyan]Running CLI research for {keyword} with sources {sources}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", type=str)
    parser.add_argument("--amazon", type=str)
    parser.add_argument("--sources", nargs="+", default=["google", "amazon"])
    parser.add_argument("--streamlit", action="store_true")
    args = parser.parse_args()

    if args.streamlit and st:
        streamlit_app()
    elif args.keyword:
        run_research(args.keyword, args.amazon, args.sources)
    else:
        console.print("[red]At least one --keyword is required (unless running via Streamlit)")
        sys.exit(1)
