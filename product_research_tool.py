#!/usr/bin/env python3
"""
Product Research Tool – v2.1
===========================
Minor patch so the script automatically **falls back to the Streamlit UI** whenever it’s executed *without* command‑line flags (the exact situation on Streamlit Community Cloud).

No more blank page – just deploy, refresh, and you’ll see the keyword box.

Changelog
---------
* **Auto‑UI fallback**: if the program detects it is running under Streamlit (module loaded) and the user supplied **no --keyword / --schedule flags**, it now calls `streamlit_app()` instead of exiting.
* Bumped version string to v2.1.
* Kept all other functionality untouched.

🛈  You don’t need to add `--streamlit` in Cloud settings anymore, but that flag still works and overrides the fallback if you prefer.

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
except ImportError:  # pragma: no cover
    st = None  # type: ignore
    alt = None  # type: ignore

console = Console()
DATA_DIR = Path("reports")

# -----------------------------------------------------------------------------
# Google Trends
# -----------------------------------------------------------------------------

def fetch_google_trends(keyword: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return interest‑over‑time and rising queries for *keyword* (5 yr window)."""
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload([keyword], timeframe="today 5-y")
    interest = pytrends.interest_over_time().reset_index()
    rising = pytrends.related_queries()[keyword]["rising"]
    return interest, rising

# -----------------------------------------------------------------------------
# Amazon Best‑Sellers
# -----------------------------------------------------------------------------

def scrape_amazon_bestsellers(category_url: str, n: int = 20) -> pd.DataFrame:
    """Scrape *n* rows from an Amazon Best‑Sellers page."""
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(category_url, headers=headers, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    for item in soup.select(".zg-grid-general-faceout")[:n]:
        rank = int(item.select_one(".zg-bdg-text").text.strip("#"))
        title_sel = item.select_one(
            ".p13n-sc-truncate-desktop-type2, ._cDEzb_p13n-sc-css-line-clamp-3_g3dy1"
        )
        title = title_sel.get_text(strip=True) if title_sel else "?"
        url = "https://www.amazon.com" + item.find("a", href=True)["href"].split("?ref")[0]
        price_tag = item.select_one("span.a-price > span.a-offscreen")
        price = price_tag.text if price_tag else "NA"
        rating_tag = item.select_one("span.a-icon-alt")
        rating = float(rating_tag.text.split()[0]) if rating_tag else None
        reviews_tag = item.select_one("span.a-size-small")
        reviews = int(reviews_tag.text.replace(",", "")) if reviews_tag else 0
        rows.append(
            {
                "rank": rank,
                "title": title,
                "price": price,
                "rating": rating,
                "reviews": reviews,
                "url": url,
            }
        )
    return pd.DataFrame(rows)

# -----------------------------------------------------------------------------
# eBay Trending
# -----------------------------------------------------------------------------

def scrape_ebay_trending() -> List[str]:
    url = "https://www.ebay.com/trending"
    r = requests.get(url, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    return [li.get_text(strip=True) for li in soup.select("ul.trending-list li a")[:20]]

# -----------------------------------------------------------------------------
# AliExpress Top Sellers
# -----------------------------------------------------------------------------

def scrape_aliexpress_top(keyword: str, n: int = 20) -> pd.DataFrame:
    search_url = (
        f"https://www.aliexpress.com/wholesale?SearchText="
        f"{requests.utils.quote(keyword)}&sortType=total_tranpro_desc"
    )
    r = requests.get(search_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for card in soup.select("div.list-item")[:n]:
        title = card.get("title") or card.select_one(".multi--titleText--text").text
        orders_tag = card.select_one("span.multi--trade--text")
        orders = (
            int(re.search(r"(\d+[\,\d]*)", orders_tag.text).group(1).replace(",", ""))
            if orders_tag
            else 0
        )
        price_tag = card.select_one(".multi--price-sale--text")
        price = price_tag.text if price_tag else "NA"
        url_tag = card.find("a", href=True)
        url = "https:" + url_tag["href"] if url_tag else ""
        items.append({"title": title, "orders": orders, "price": price, "url": url})
    return pd.DataFrame(items)

# -----------------------------------------------------------------------------
# TikTok Trending
# -----------------------------------------------------------------------------

def scrape_tiktok_trending(n: int = 20) -> List[str]:
    explore_url = "https://www.tiktok.com/api/discover/item_list/?count=30&region=US"
    try:
        r = requests.get(explore_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        return [item.get("text", "") for item in data.get("itemList", [])][:n]
    except Exception:  # noqa: BLE001
        return []

# -----------------------------------------------------------------------------
# Metrics helpers
# -----------------------------------------------------------------------------

def demand_score(interest: pd.DataFrame) -> float:
    """YoY growth (‑1..+1)."""
    if interest.empty:
        return 0.0
    last_year = interest.tail(52)[interest.columns[1]].mean()
    prev_year = interest.tail(104).head(52)[interest.columns[1]].mean()
    return round((last_year - prev_year) / (prev_year or 1e-6), 2)


def competition_gauge(amazon_df: pd.DataFrame) -> int:
    """Median review count."""
    return int(amazon_df["reviews"].median()) if not amazon_df.empty else 0

# -----------------------------------------------------------------------------
# IO helpers
# -----------------------------------------------------------------------------

def save_csv(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def email_digest(
    subject: str, body: str, attachment_paths: List[Path], smtp_cfg: dict, to_addr: str
):
    msg = MIMEMultipart()
    msg["From"] = smtp_cfg["user"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    for path in attachment_paths:
        with open(path, "rb") as f:
            part = MIMEApplication(f.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)
    with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"]) as server:
        server.starttls()
        server.login(smtp_cfg["user"], smtp_cfg["password"])
        server.send_message(msg)

# -----------------------------------------------------------------------------
# Core research
# -----------------------------------------------------------------------------

def run_research(keyword: str, amazon_url: str | None, sources: List[str]) -> Path:
    console.rule(f"[bold cyan]Research: {keyword}")
    report_dir = DATA_DIR / keyword.replace(" ", "_")
    report_dir.mkdir(parents=True, exist_ok=True)

    # Google
    if "google" in sources:
        interest, rising = fetch_google_trends(keyword)
        save_csv(interest, report_dir / "google_interest.csv")
        save_csv(rising, report_dir / "google_rising.csv")
    else:
        interest, rising = pd.DataFrame(), pd.DataFrame()

    # Amazon
    if amazon_url and "amazon" in sources:
        amazon_df = scrape_amazon_bestsellers(amazon_url)
        save_csv(amazon_df, report_dir / "amazon_bestsellers.csv")
    else:
        amazon_df = pd.DataFrame()

    # eBay
    if "ebay" in sources:
        ebay_list = scrape_ebay_trending()
        save_csv(pd.DataFrame({"trending": ebay_list}), report_dir / "ebay_trending.csv")

    # AliExpress
    if "aliexpress" in sources:
        ali_df = scrape_aliexpress_top(keyword)
        save_csv(ali_df, report_dir / "aliexpress_top.csv")

    # TikTok
    if "tiktok" in sources:
        tiktok_list = scrape_tiktok_trending()
        save_csv(pd.DataFrame({"trending": tiktok_list}), report_dir / "tiktok_trending.csv")

    # Summary
    summary_path = report_dir / "summary.csv"
    summary = pd.DataFrame(
        [
            {
                "keyword": keyword,
                "demand_score": demand_score(interest),
                "competition_gauge": competition_gauge(amazon_df),
                "timestamp": dt.datetime.now().isoformat(),
            }
        ]
    )
    save_csv(summary, summary_path)
    console.print(summary)
    return summary_path

# -----------------------------------------------------------------------------
# Scheduler
# -----------------------------------------------------------------------------

def schedule_jobs(
    keywords: List[str],
    amazon_url: str,
    sources: List[str],
    cron_expr: str,
    email_to: str,
    smtp_cfg: dict,
):
    scheduler = BackgroundScheduler()

    def task():
        attachments: List[Path] = []
        body_lines: List[str] = []
        for kw in keywords:
            summary_file = run_research(kw, amazon_url, sources)
            attachments.append(summary_file)
            df = pd.read_csv(summary_file)
            body_lines.append(df.to_string(index=False))
        body = "\n\n".join(body_lines)
        subject = f"Weekly Product Research Digest – {dt.date.today()}"
        email_digest(subject, body, attachments, smtp_cfg, email_to)
        console.log("[green]Digest emailed!")

    minute, hour, dom, month, dow = cron_expr.split()
    scheduler.add_job(
        task, "cron", minute=minute, hour=hour, day=dom, month=month, day_of_week=dow
    )
    console.log(
        f"[yellow]Scheduled weekly monitoring ({cron_expr}) for {', '.join(keywords)}"
    )
    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

# -----------------------------------------------------------------------------
# Streamlit UI
# -----------------------------------------------------------------------------

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
        if google_chk:
            sources.append("google")
        if amazon_chk:
            sources.append("amazon")
        if ebay_chk:
            sources.append("ebay")
        if ali_chk:
            sources.append("aliexpress

