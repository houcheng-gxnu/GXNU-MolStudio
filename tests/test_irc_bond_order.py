# -*- coding: utf-8 -*-
"""IRC regression checks; no external Multiwfn installation is required."""
import hashlib
import os
import subprocess
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from molstudio.core import fchk_orbital
from molstudio.panels import irc_panel as irc


MAYER_OUTPUT = (
    "Bond orders with absolute value greater than 0.050000\n"
    " #    1:         1(C )    2(O )    2.24690074\n"
    " #    2:         1(C )    3(H )    0.98765432\n"
)


def test_launch_and_reuse_all_pairs(tmp_path, monkeypatch):
    data_dir = tmp_path / "IRC files"
    data_dir.mkdir()
    fchk = data_dir / "point 01.fchk"
    fchk.touch()
    exe = tmp_path / "Multiwfn.exe"
    exe.touch()
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, MAYER_OUTPUT, "")

    monkeypatch.setattr(fchk_orbital.subprocess, "run", fake_run)
    output = irc.calculate_mayer_bond_order(str(fchk), str(exe), str(tmp_path / "cache"))
    assert irc.extract_bond_from_output(output, "1", "2") == pytest.approx(2.24690074)
    cached = irc.calculate_mayer_bond_order(str(fchk), str(exe), str(tmp_path / "cache"))
    assert irc.extract_bond_from_output(cached, "3", "1") == pytest.approx(0.98765432)
    assert len(calls) == 1  # Adding another pair must not launch Multiwfn again.
    args, kwargs = calls[0]
    assert args == [str(exe), fchk.name]
    assert kwargs["cwd"] == str(data_dir)
    assert kwargs["input"] == irc.BO_INPUT_SEQ
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.PIPE
    if os.name == "nt":
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP


def test_menu_only_cache_is_not_reused(tmp_path, monkeypatch):
    fchk = tmp_path / "point.fchk"
    exe = tmp_path / "Multiwfn.exe"
    fchk.touch()
    exe.touch()
    key = hashlib.md5(str(fchk).encode()).hexdigest()[:8]
    cache_file = tmp_path / ("mayer_%s.txt" % key)
    cache_file.write_text("Bond orders menu\n" * 20, encoding="utf-8")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 0, MAYER_OUTPUT, "")

    monkeypatch.setattr(irc, "_run_multiwfn_subprocess", fake_run)
    assert irc.calculate_mayer_bond_order(str(fchk), str(exe), str(tmp_path)) == MAYER_OUTPUT
    assert len(calls) == 1
    assert cache_file.read_text(encoding="utf-8") == MAYER_OUTPUT


@pytest.mark.parametrize("failure", ["timeout", "menu", "exit"])
def test_failed_invocation_stops_batch(tmp_path, monkeypatch, failure):
    exe = tmp_path / "Multiwfn.exe"
    exe.touch()
    files = []
    for i in range(3):
        fp = tmp_path / ("point%d.fchk" % i)
        fp.touch()
        files.append(str(fp))
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        if failure == "timeout":
            raise subprocess.TimeoutExpired("Multiwfn", 300)
        if failure == "menu":
            return subprocess.CompletedProcess([], 0, "Choose an input file\n" * 20, "")
        return subprocess.CompletedProcess([], 1, MAYER_OUTPUT, "invalid input")

    monkeypatch.setattr(irc, "_run_multiwfn_subprocess", fake_run)
    worker = irc.IrcBondWorker(files, str(exe), str(tmp_path / "cache"), "1", "2")
    errors, completed = [], []
    worker.error_signal.connect(errors.append)
    worker.finished_signal.connect(completed.append)
    worker.run()
    assert len(calls) == 1  # Do not repeat the same failure on every IRC point.
    assert len(errors) == 1
    assert "point0.fchk" in errors[0]
    assert completed == [[None, None, None]]
    assert not list((tmp_path / "cache").glob("mayer_*.txt"))


def test_each_point_is_processed_once(tmp_path, monkeypatch):
    calls = []

    def calculate(fp, *_args):
        calls.append(fp)
        return MAYER_OUTPUT

    monkeypatch.setattr(irc, "calculate_mayer_bond_order", calculate)
    worker = irc.IrcBondWorker(["point1.fchk", "point2.fchk"], "Multiwfn", str(tmp_path), "1", "2")
    completed = []
    worker.finished_signal.connect(completed.append)
    worker.run()
    assert calls == ["point1.fchk", "point2.fchk"]
    assert completed == [[pytest.approx(2.24690074), pytest.approx(2.24690074)]]


@pytest.mark.parametrize("values", [[1.2, 1.1], [None, None]])
def test_completion_preserves_existing_curves(values):
    enabled, updates = [], []
    first = {"name": "1-2", "values": [2.2, 2.1]}
    panel = SimpleNamespace(
        btn_add_bond=SimpleNamespace(setEnabled=enabled.append),
        _log=lambda _message: None,
        all_bond_data=[first],
        all_charge_data=[],
        _update_bond_list=lambda: updates.append("list"),
        _update_plot=lambda: updates.append("plot"),
    )
    irc.IrcPanel._on_bond_done(panel, values, "1", "3")
    assert enabled == [True]
    assert panel.all_bond_data[0] is first
    if any(value is not None for value in values):
        assert len(panel.all_bond_data) == 2
        assert panel.all_bond_data[1]["values"] == values
        assert panel.all_bond_data[1]["color"] == irc.BOND_COLORS[1]
        assert updates == ["list", "plot"]
    else:
        assert panel.all_bond_data == [first]
        assert updates == []
