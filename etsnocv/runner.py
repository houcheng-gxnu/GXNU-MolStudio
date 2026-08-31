# -*- coding: utf-8 -*-
"""
Multiwfn runner — subprocess management and QThread workers for ETS-NOCV.
Supports both one-shot (MultiwfnRunner) and persistent session (MultiwfnSession).
"""

import os
import threading
import time
import subprocess
import traceback

from PyQt5.QtCore import QThread, pyqtSignal


# ── Legacy one-shot runner (kept for backward compatibility) ──────────────

class MultiwfnRunner:
    def __init__(self):
        self._proc = None

    def run(self, exe_path, input_seq, timeout=1200, cwd=None):
        try:
            self._proc = subprocess.Popen(
                exe_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                cwd=cwd,
            )
            stdout, _ = self._proc.communicate(input=input_seq, timeout=timeout)
            return stdout
        except subprocess.TimeoutExpired:
            self.kill()
            return None
        except Exception:
            traceback.print_exc()
            return None
        finally:
            self._proc = None

    def kill(self):
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            self._proc = None


class CalcWorker(QThread):
    finished = pyqtSignal(object)

    def __init__(self, runner, exe, input_seq, work_dir):
        super().__init__()
        self.runner = runner
        self.exe = exe
        self.input_seq = input_seq
        self.work_dir = work_dir

    def run(self):
        output = self.runner.run(self.exe, self.input_seq, cwd=self.work_dir)
        self.finished.emit(output)


# ── Persistent Multiwfn session (on-demand cube generation) ──────────────

def _detect_encoding():
    """Detect system encoding via chcp (avoids locale module conflict)."""
    try:
        import subprocess as sp
        result = sp.run(["chcp"], capture_output=True, text=True, shell=True)
        if "936" in result.stdout:
            return "gbk"
        elif "65001" in result.stdout:
            return "utf-8"
    except:
        pass
    return "utf-8"


class MultiwfnSession:
    """Long-lived Multiwfn process with background stdout reader.
    
    Starts Multiwfn with text-mode pipes (using system encoding),
    continuously reads stdout in a background thread, and provides
    methods to write commands and wait for output patterns.
    """

    def __init__(self):
        self._proc = None
        self._buffer = ""
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._menu_count = 0
        self._reader_thread = None
        self._encoding = "utf-8"

    def start(self, exe_path, cwd=None, encoding=None):
        if encoding is None:
            encoding = _detect_encoding()
        self._encoding = encoding
        
        # Set Multiwfnpath environment variable
        env = os.environ.copy()
        env["Multiwfnpath"] = os.path.dirname(os.path.abspath(exe_path))
        
        self._proc = subprocess.Popen(
            [exe_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
            cwd=cwd,
            env=env,
        )
        import time
        time.sleep(0.5)
        if self._proc.poll() is not None:
            raise RuntimeError(f"Multiwfn exited immediately with code {self._proc.returncode}")
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self):
        try:
            for line in self._proc.stdout:
                if not line:
                    break
                with self._cond:
                    self._buffer += line
                    if "Post-processing menu" in line:
                        self._menu_count += 1
                    self._cond.notify_all()
        except Exception:
            pass

    def write(self, text):
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("Multiwfn process is no longer running")
        self._proc.stdin.write(text)
        self._proc.stdin.flush()

    def wait_for_menu(self, timeout=300, min_menus=1):
        """Wait until at least min_menus menus have appeared in stdout."""
        with self._cond:
            start = time.time()
            while self._menu_count < min_menus:
                remaining = timeout - (time.time() - start)
                if remaining <= 0:
                    return False
                self._cond.wait(timeout=min(remaining, 1.0))
            return True

    def wait_for(self, pattern, timeout=60, after=0):
        """等待 buffer 中（位置 after 之后）出现 pattern，返回出现位置或 -1。"""
        with self._cond:
            start = time.time()
            while True:
                idx = self._buffer.find(pattern, after)
                if idx >= 0:
                    return idx
                remaining = timeout - (time.time() - start)
                if remaining <= 0:
                    return -1
                self._cond.wait(timeout=min(remaining, 0.5))

    def wait_for_any(self, patterns, timeout=60, after=0):
        """等待 buffer 中（位置 after 之后）出现任一 pattern，返回命中的 pattern 或 None。"""
        with self._cond:
            start = time.time()
            while True:
                for pat in patterns:
                    if self._buffer.find(pat, after) >= 0:
                        return pat
                remaining = timeout - (time.time() - start)
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=min(remaining, 0.5))

    @property
    def buffer(self):
        with self._cond:
            return self._buffer

    def is_alive(self):
        return self._proc is not None and self._proc.poll() is None

    def shutdown(self):
        if self._proc and self._proc.poll() is None:
            self.write("q\n-10\nq\n")
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None


class SetupWorker(QThread):
    """Starts Multiwfn, sends NOCV setup commands, keeps session alive."""
    finished = pyqtSignal(object, object, str)  # output_text, session, error_msg
    log = pyqtSignal(str)

    def __init__(self, exe_path, complex_path, frag1_path, frag2_path, 
                 spin_answers, tmp_dir, parent=None):
        super().__init__(parent)
        self.exe_path = exe_path
        self.complex_path = complex_path
        self.frag1_path = frag1_path
        self.frag2_path = frag2_path
        self.spin_answers = spin_answers
        self.tmp_dir = tmp_dir
        self.session = None
        self._stopped = False

    def stop(self):
        """Stop the running analysis - shutdown Multiwfn session."""
        self._stopped = True
        if self.session is not None:
            self.session.shutdown()
            self.session = None

    def build_script(self):
        """Build NOCV setup script (NO -10/q, keeps Multiwfn alive)."""
        import os
        lines = []
        lines.append(os.path.basename(self.complex_path))
        lines.append("23")
        lines.append("2")
        lines.append(os.path.basename(self.frag1_path))
        lines.append(os.path.basename(self.frag2_path))
        # Only send spin flip answers for open-shell fragments
        # Closed-shell: Multiwfn doesn't ask, so we skip
        if self.spin_answers is not None:
            for ans in self.spin_answers:
                lines.append("y" if ans else "n")
        lines.append("-2")
        return "\n".join(lines) + "\n"

    def run(self):
        script = self.build_script()
        self.log.emit(f"[Setup] Starting Multiwfn: {self.exe_path}")
        self.log.emit(f"[Setup] Working directory: {self.tmp_dir}")
        self.log.emit(f"[Setup] Script to send:\n{script}")

        session = MultiwfnSession()
        try:
            session.start(self.exe_path, cwd=self.tmp_dir)
        except Exception as e:
            self.log.emit(f"[Setup] Failed to start: {e}")
            self.finished.emit(None, None, str(e))
            return

        self.session = session
        if self._stopped:
            session.shutdown()
            self.session = None
            self.finished.emit(None, None, "Stopped by user")
            return
        self.log.emit("[Setup] Process started, sending commands...")

        # Write all setup commands at once
        session.write(script)
        self.log.emit("[Setup] Commands sent, waiting for Post-processing menu (2nd)...")

        # Wait for second Post-processing menu (after -2 generates Fock matrix)
        if not session.wait_for_menu(timeout=600, min_menus=2):
            self.log.emit("[Setup] TIMEOUT waiting for Post-processing menu")
            self.log.emit(f"[Setup] Buffer (last 1000):\n{session.buffer[-1000:]}")
            session.shutdown()
            self.session = None
            self.finished.emit(None, None, "Setup timeout")
            return

        output = session.buffer
        menu_count = output.count("Post-processing menu")
        self.log.emit(f"[Setup] Done! 'Post-processing menu' appeared {menu_count} times.")
        self.log.emit(f"[Setup] Output: {len(output)} chars, session alive: {session.is_alive()}")
        self.finished.emit(output, session, "")


class CubeGenWorker(QThread):
    """Generates NOCV pair density cube(s) from a persistent Multiwfn session.
    
    pair_selector: str - single "1" or Multiwfn-style range "3-6,8", passed directly to Multiwfn.
    """
    finished = pyqtSignal(str, str, str)   # cube_path, pair_selector, output_delta
    error = pyqtSignal(str, str)           # error_message, pair_selector
    log = pyqtSignal(str)                  # debug log

    def __init__(self, session, pair_selector, grid_quality, cub_name, tmp_dir, parent=None):
        super().__init__(parent)
        self.session = session
        self.pair_selector = str(pair_selector)  # string: "1" or "3-6" or "3-6,8,10-12"
        self.grid_quality = grid_quality
        self.cub_name = cub_name
        self.tmp_dir = tmp_dir

    def run(self):
        cub_path = os.path.join(self.tmp_dir, self.cub_name)
        
        # Remove existing cube file to avoid stale file detection
        if os.path.exists(cub_path):
            try:
                os.remove(cub_path)
                self.log.emit(f"[Cube] Removed existing: {cub_path}")
            except OSError:
                pass
        
        # Check session health
        if not self.session.is_alive():
            self.log.emit(f"[Cube] Session is DEAD, cannot generate cube")
            self.error.emit("Multiwfn session has ended. Please re-run ETS-NOCV analysis.", self.pair_selector)
            return
        
        # Capture buffer BEFORE sending cube command (for output delta)
        output_before = self.session.buffer
        
        # ── 提示驱动（prompt-driven）交互 ──
        # 不同 Multiwfn 版本在 option 7 后的行为不同：
        #   * 旧版本：每次都询问网格 → 序列 7 → 网格 → pair → 计算 → 文件名
        #   * 本机 2026.4.10：网格设置保持，第二次不再询问 → 序列 7 → pair → 计算 → 文件名
        # 硬编码哪种都会在另一台机器上把输入错位（把文件名当 pair 读 → Multiwfn 崩溃）。
        # 因此根据 Multiwfn 实际弹出的提示应答：等「网格」或「pair」提示谁先出现，
        # 有网格就答网格，再答 pair，最后等「文件名」提示答文件名。
        GRID_P = "Please select a method to set up grid"
        PAIR_P = "Input the index of the NOCV pair"
        FILE_P = "Input the file path for outputting the cube file"
        try:
            self.session.write("7\n")
            pos = len(self.session.buffer)
            p = self.session.wait_for_any([GRID_P, PAIR_P], timeout=30, after=pos)
            if p is None:
                self.log.emit("[Cube] No grid/pair prompt after '7' (unknown menu state)")
                self.error.emit(
                    "Multiwfn did not show the expected prompt after '7' — "
                    "the session may be in the wrong menu; re-run the analysis",
                    self.pair_selector)
                return
            if p == GRID_P:
                grid = self.grid_quality if self.grid_quality is not None else 2
                self.session.write(str(grid) + "\n")
                pos = len(self.session.buffer)
                if self.session.wait_for(PAIR_P, timeout=30, after=pos) < 0:
                    self.error.emit("Multiwfn did not ask for the NOCV pair after grid", self.pair_selector)
                    return
            self.session.write(self.pair_selector + "\n")
            # pair 之后要等计算完成才会出现文件名提示（大网格可能较久）
            pos = len(self.session.buffer)
            if self.session.wait_for(FILE_P, timeout=600, after=pos) < 0:
                self.error.emit(
                    "Multiwfn did not ask for the cube file name (grid calc may have failed)",
                    self.pair_selector)
                return
            self.session.write(self.cub_name + "\n")
            self.log.emit(f"[Cube] Command sent, waiting for file...")
        except Exception as e:
            self.log.emit(f"[Cube] Failed to drive Multiwfn: {e}")
            self.error.emit(f"Failed to communicate with Multiwfn: {e}", self.pair_selector)
            return

        timeout = 120
        interval = 0.5
        elapsed = 0.0
        while elapsed < timeout:
            # 会话中途死亡 → 提前退出，不必干等超时
            if not self.session.is_alive():
                self.log.emit("[Cube] Session died during cube generation")
                self.error.emit(
                    "Multiwfn session ended during cube generation — re-run the analysis",
                    self.pair_selector)
                return
            if os.path.exists(cub_path) and os.path.getsize(cub_path) > 0:
                # 等文件大小稳定（Multiwfn 可能仍在写入，直接发 q 会竞态）
                last = os.path.getsize(cub_path)
                stable_for = 0
                while stable_for < 3:
                    time.sleep(0.5)
                    if os.path.exists(cub_path) and os.path.getsize(cub_path) == last:
                        stable_for += 1
                    else:
                        last = os.path.getsize(cub_path) if os.path.exists(cub_path) else 0
                        stable_for = 0
                self.log.emit(f"[Cube] File stable: {cub_path} ({last} bytes)")
                # Restore Multiwfn to Post-processing menu
                self.session.write("q\n")
                self.log.emit(f"[Cube] Sent 'q' to return to menu, done!")
                
                # Wait for Multiwfn to finish writing cube + process 'q'
                time.sleep(0.5)
                output_after = self.session.buffer
                output_delta = output_after[len(output_before):] if len(output_after) > len(output_before) else ""
                
                self.finished.emit(cub_path, self.pair_selector, output_delta)
                return
            time.sleep(interval)
            elapsed += interval

        self.log.emit(f"[Cube] TIMEOUT after {timeout}s, file not found: {cub_path}")
        # 附带 Multiwfn 输出尾部，方便定位（如路径/权限/版本导致的失败）
        tail = self.session.buffer[len(output_before):] if len(self.session.buffer) > len(output_before) else ""
        if not tail:
            tail = self.session.buffer[-500:]
        self.error.emit(
            f"Cube generation timeout for pair {self.pair_selector}\n"
            f"expected file: {cub_path}\n"
            f"Multiwfn output tail:\n{tail[-500:]}",
            self.pair_selector)
