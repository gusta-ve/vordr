from vordr.format import (
    days_left_label,
    days_left_style,
    human_age,
    human_kb,
    human_uptime,
    load_style,
    pct_style,
)


def test_human_uptime_levels():
    assert human_uptime(None) == "—"
    assert human_uptime(-5) == "—"
    assert human_uptime(0) == "0m"
    assert human_uptime(90) == "1m"
    assert human_uptime(3600) == "1h"
    assert human_uptime(86400) == "1d"
    # 2 weeks, 5 days, 2 hours -> only the 3 largest components
    secs = 2 * 604800 + 5 * 86400 + 2 * 3600 + 54 * 60
    assert human_uptime(secs) == "2w 5d 2h"


def test_human_kb():
    assert human_kb(None) == "—"
    assert human_kb(512) == "512KB"
    assert human_kb(2048) == "2.0MB"
    assert human_kb(1024 * 1024) == "1.0GB"


def test_human_age():
    assert human_age(None) == "—"
    assert human_age(-1) == "—"
    assert human_age(10) == "10d"        # less than a month
    assert human_age(60) == "2mo"
    assert human_age(365) == "1y"
    assert human_age(365 + 90) == "1y 3mo"


def test_pct_style_thresholds():
    assert pct_style(None) == "dim"
    assert pct_style(10) == "green"
    assert pct_style(80) == "yellow"
    assert pct_style(95) == "bold red"


def test_load_style():
    assert load_style(None) == "dim"
    assert load_style(0.2) == "green"
    assert load_style(0.8) == "yellow"
    assert load_style(1.5) == "bold red"


def test_days_left_style_and_label():
    assert days_left_style(None, warn=14, critical=7) == "dim"
    assert days_left_style(-1, warn=14, critical=7) == "bold red"
    assert days_left_style(3, warn=14, critical=7) == "bold red"
    assert days_left_style(10, warn=14, critical=7) == "yellow"
    assert days_left_style(40, warn=14, critical=7) == "green"

    assert days_left_label(None) == "—"
    assert days_left_label(0) == "due today"
    assert days_left_label(5) == "5d"
    assert days_left_label(-2) == "2d overdue"
