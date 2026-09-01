"""
workers: 后台工作线程
提供 CubeWorker (生成cube) 和 RenderWorker (Tachyon 渲染)。
"""

import os
import time

from PyQt5.QtCore import QThread, pyqtSignal

from i18n import tr


class CubeWorker(QThread):
    """Background worker for cube generation."""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, int, int, list)

    def __init__(self, files, out_dir, orbitals, iso, grid, style_name,
                 resolution, shade_mode, auto_render, exe_paths, do_open):
        super().__init__()
        self.files = files
        self.out_dir = out_dir
        self.orbitals = orbitals
        self.iso = iso
        self.grid = grid
        self.style_name = style_name
        self.resolution = resolution
        self.shade_mode = shade_mode
        self.auto_render = auto_render
        self.exe_paths = exe_paths
        self.do_open = do_open
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        import fchk_orbital as backend

        total = len(self.files)
        is_multi = len(self.orbitals) > 1
        orbital = self.orbitals[0] if self.orbitals else ""

        self.log_signal.emit(tr("log_worker_start", total=total, out_dir=self.out_dir))
        if is_multi:
            self.log_signal.emit(
                tr("log_worker_params_multi",
                   orbitals=','.join(self.orbitals), iso=self.iso,
                   grid=self.grid, style=self.style_name,
                   res=f"{self.resolution[0]}x{self.resolution[1]}"))
        else:
            self.log_signal.emit(
                tr("log_worker_params_single",
                   orbital=orbital, iso=self.iso, grid=self.grid,
                   style=self.style_name,
                   res=f"{self.resolution[0]}x{self.resolution[1]}"))
        if self.auto_render:
            self.log_signal.emit(tr("log_worker_mode_auto"))
        else:
            self.log_signal.emit(tr("log_worker_mode_manual"))
        self.log_signal.emit("=" * 50)

        ok = 0
        cubes = []
        t_total = time.time()
        for i, fchk in enumerate(self.files):
            if not self._running:
                self.log_signal.emit(tr("log_worker_stopped"))
                break
            name = os.path.basename(fchk)
            self.progress_signal.emit(f"[{i+1}/{total}] {name}")
            self.log_signal.emit(f"\n[{i+1}/{total}] {name}")

            t0 = time.time()
            cube_result = None
            if is_multi:
                results = backend.gen_multi_cubes(
                    fchk, self.orbitals,
                    grid_quality=int(self.grid), work_dir=self.out_dir,
                    multiwfn_exe=self.exe_paths["multiwfn"])
                dt = time.time() - t0
                if results:
                    for cube_path, orb_name in results:
                        self.log_signal.emit(
                            tr("log_worker_cube_ok_orb", orb=orb_name, path=os.path.basename(cube_path)))
                        cubes.append((cube_path, orb_name))
                    ok += 1
                    cube_result = results[0][0] if results else None
                else:
                    self.log_signal.emit(tr("log_worker_cube_fail_dt", dt=dt))
            else:
                result = backend.gen_cube(
                    fchk, orbital=orbital,
                    grid_quality=int(self.grid), work_dir=self.out_dir,
                    multiwfn_exe=self.exe_paths["multiwfn"])
                cube_result = result
                dt = time.time() - t0
                if not result:
                    self.log_signal.emit(tr("log_worker_cube_fail_dt2", dt=dt))
                    continue
                self.log_signal.emit(
                    tr("log_worker_cube_ok_dt", dt=dt, path=os.path.basename(result)))
                cubes.append(result)
                ok += 1

            if self.auto_render and cube_result:
                t0 = time.time()
                try:
                    png = self._fchk_to_png_name(fchk)
                    backend.render_cube_auto(
                        cube_result, output_png=png, isovalue=self.iso,
                        style_name=self.style_name, resolution=self.resolution,
                        vmd_exe=self.exe_paths["vmd"],
                        tachyon_exe=self.exe_paths["tachyon"],
                        shade_mode=self.shade_mode)
                    dt = time.time() - t0
                    self.log_signal.emit(f"  PNG: {os.path.basename(png)} ({dt:.1f}s)")
                except Exception as e:
                    self.log_signal.emit(tr("log_worker_render_error", e=e))

        elapsed = time.time() - t_total
        self.log_signal.emit(
            tr("log_worker_done_summary", ok=ok, total=total, elapsed=elapsed))
        self.finished_signal.emit(self.auto_render, ok, total, cubes)

    def _fchk_to_png_name(self, fchk_path):
        orbital = ",".join(self.orbitals) if len(self.orbitals) > 1 else self.orbitals[0]
        stem = os.path.splitext(os.path.basename(fchk_path))[0]
        return os.path.join(self.out_dir, f"{stem}_MO{orbital}.png")


class RenderWorker(QThread):
    """Background worker for Tachyon scene rendering."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)

    def __init__(self, port, render_dir, output_png, tachyon_exe, resolution,
                 style_name="sob-art", shade_mode="full", trans_mode=None,
                 num_threads=8):
        super().__init__()
        self.port = port
        self.render_dir = render_dir
        self.output_png = output_png
        self.tachyon_exe = tachyon_exe
        self.resolution = resolution
        self.style_name = style_name
        self.shade_mode = shade_mode
        self.trans_mode = trans_mode
        self.num_threads = num_threads

    def run(self):
        import fchk_orbital as backend

        self.log_signal.emit(tr("log_render_start", style=self.style_name))
        t0 = time.time()
        try:
            png = backend.render_current_view(
                self.port, self.render_dir, output_png=self.output_png,
                resolution=self.resolution,
                tachyon_exe=self.tachyon_exe,
                style_name=self.style_name,
                shade_mode=self.shade_mode,
                trans_mode=self.trans_mode,
                threads=self.num_threads,
                log_func=lambda msg: self.log_signal.emit(msg))
            dt = time.time() - t0
            if png and os.path.exists(png):
                self.log_signal.emit(tr("log_render_done", dt=dt, path=os.path.basename(png)))
            else:
                self.log_signal.emit(tr("log_render_fail", dt=dt))
            self.finished_signal.emit(png if png else "")
        except Exception as e:
            self.log_signal.emit(tr("log_render_err", e=e))
            self.finished_signal.emit("")


class SpinDensityWorker(QThread):
    """后台生成自旋密度 cube（Multiwfn，提示驱动）。"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)   # 0-100
    finished_signal = pyqtSignal(str)   # cube 路径
    error_signal = pyqtSignal(str)

    def __init__(self, fchk_path, multiwfn_exe, work_dir=None,
                 grid_quality=3, parent=None):
        super().__init__(parent)
        self.fchk_path = fchk_path
        self.multiwfn_exe = multiwfn_exe
        self.work_dir = work_dir
        self.grid_quality = grid_quality
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        import fchk_orbital as backend

        try:
            cube = backend.gen_spin_cube(
                self.fchk_path, multiwfn_exe=self.multiwfn_exe,
                work_dir=self.work_dir, grid_quality=self.grid_quality,
                log_func=lambda ln: self.log_signal.emit(ln) if self._running else None,
                progress_cb=lambda pct, ln: self.progress_signal.emit(int(pct))
                if self._running else None,
                cancel_check=lambda: not self._running)
            if cube and os.path.exists(cube):
                self.finished_signal.emit(cube)
            else:
                self.error_signal.emit(tr("spin_density_failed"))
        except Exception as e:
            self.error_signal.emit(str(e))
