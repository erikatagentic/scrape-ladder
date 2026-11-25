"""The public check. Planted values are built from pieces so this file itself stays clean."""
import importlib.util

import pytest

from .conftest import ROOT, ip

spec = importlib.util.spec_from_file_location("check_public", ROOT / "scripts" / "check_public.py")
check_public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_public)

AT = "@"


@pytest.mark.parametrize(
    "line, label",
    [
        ("call " + "860" + "-555-" + "0142", "phone number"),
        ("host " + ip(10, 2, 3, 4), "private IP"),
        ("host " + ip(192, 168, 7, 1), "private IP"),
        ("host " + ip(172, 20, 0, 3), "private IP"),
        ("see https://my-worker" + ".onrender" + ".com/health", "internal host"),
        ("see https://my-app" + ".fly" + ".dev", "internal host"),
        ("see https://flows-n8n" + ".somewhere" + ".io/", "internal host"),
        ("post to https://hooks" + ".slack" + ".com/services/x", "chat webhook"),
        ("SERVICE" + "_TOKEN=" + "x" * 24, "key with a value"),
        ("api" + "_key: " + "y" * 12, "key with a value"),
        ("mail jo" + AT + "realcompany" + ".com", "email"),
    ],
)
def test_each_kind_of_leak_is_flagged(line, label):
    hits = check_public.scan_text(line)
    assert [h[1] for h in hits] == [label]


@pytest.mark.parametrize(
    "line",
    [
        "erik" + AT + "erikhernal.com",
        "desk" + AT + "news.example.com",
        "help" + AT + "shop.example",
        "ops" + AT + "fixture.test",
        "127.0.0.1 and 169.254.169.254 and 93.184.215.14",
        "SERVICE" + "_TOKEN is read from the environment",
        "version 1.0.2, 18.00 USD, 142 packets",
    ],
)
def test_allowed_lines_are_not_flagged(line):
    assert check_public.scan_text(line) == []


def test_key_values_are_never_printed():
    hits = check_public.scan_text("DB" + "_PASSWORD=" + "z" * 16)
    assert hits[0][2] == "[value hidden]"


def test_folder_scan_skips_virtualenvs_and_binary_files(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("jo" + AT + "realcompany" + ".com")
    (tmp_path / "blob.bin").write_bytes(b"\0" + ("jo" + AT + "realcompany" + ".com").encode())
    (tmp_path / "ok.md").write_text("clean")
    assert check_public.scan_folder(tmp_path) == []
    (tmp_path / "bad.md").write_text("line one\nhost " + ip(10, 9, 9, 9))
    assert check_public.scan_folder(tmp_path) == ["bad.md:2: private IP: " + ip(10, 9, 9, 9)]


def test_this_repo_is_clean():
    assert check_public.scan_folder(ROOT) == []
