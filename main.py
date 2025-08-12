#!/usr/bin/env python3
"""
EZMount — reliable 30% / 70% UI layout + background mounts + nircmd-aware startup scripts.

Replace your ezmount_app.py with this file and run: python ezmount_app.py
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext
from pathlib import Path
import subprocess
import threading
import shutil
import os
import time
import shlex

APP_TITLE = "EZMount"
STARTUP_PREFIX = "EZMount_"
LOG_MAX_CHARS = 15000


def parse_conf_sections(conf_text: str):
    sections = {}
    current = None
    for raw in conf_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections[current] = {}
            continue
        if current is None:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            sections[current][k.strip()] = v.strip()
    return sections


def get_startup_folder():
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    else:
        return Path.home() / ".config" / "autostart"


def ensure_startup_folder():
    p = get_startup_folder()
    if p:
        p.mkdir(parents=True, exist_ok=True)
    return p


class EZMountApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} — rclone UI")
        self.geometry("1100x700")

        self.loaded_conf_path = None
        self.loaded_conf_text = ""
        self.conf_sections = {}

        self.mappings = []
        self.active_mounts = []

        self.rclone_path = shutil.which("rclone")

        self._build_ui()
        self.after(1000, self._refresh_status_periodic)

    def _build_ui(self):
        pad = 8

        # top toolbar
        toolbar = ttk.Frame(self, padding=(pad, pad // 2))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Select rclone.conf", command=self.select_conf).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Auto-generate mappings", command=self.auto_generate_mappings).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Add mapping", command=self.add_mapping_row).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear mappings", command=self.clear_mappings).pack(side=tk.LEFT, padx=6)
        ttk.Label(toolbar, text="    ").pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Mount All", command=self.mount_all).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Unmount All", command=self.unmount_all).pack(side=tk.RIGHT, padx=6)

        self.lbl_conf = ttk.Label(toolbar, text="(no config loaded)")
        self.lbl_conf.pack(side=tk.LEFT, padx=(12, 0))
        self.lbl_rclone = ttk.Label(toolbar, text=f"rclone: {self.rclone_path or '(not found)'}")
        self.lbl_rclone.pack(side=tk.LEFT, padx=(12, 0))

        # main container (grid) for reliable 30% / 70% split
        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))

        # configure columns: use weights 3 and 7 to approximate 30/70
        main_container.columnconfigure(0, weight=3)
        main_container.columnconfigure(1, weight=7)
        main_container.rowconfigure(0, weight=1)

        # LEFT: readonly conf (30%)
        left = ttk.Frame(main_container, padding=pad)
        left.grid(row=0, column=0, sticky="nsew")
        ttk.Label(left, text="rclone.conf (read-only)", font=(None, 11, "bold")).pack(anchor="w")
        # set width so it doesn't hog horizontal space
        self.txt_conf = scrolledtext.ScrolledText(left, wrap=tk.NONE, height=30, width=60)
        self.txt_conf.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.txt_conf.configure(state=tk.DISABLED)

        # RIGHT: mappings (70%)
        right = ttk.Frame(main_container, padding=pad)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Mappings", font=(None, 11, "bold")).pack(anchor="w")

        header = ttk.Frame(right)
        header.pack(fill=tk.X, pady=(6, 4))
        header.columnconfigure(0, weight=4)
        header.columnconfigure(1, weight=2)
        header.columnconfigure(2, weight=1)
        header.columnconfigure(3, weight=1)
        header.columnconfigure(4, weight=0)
        ttk.Label(header, text="Remote[:path]").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Label").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Drive / Mount").grid(row=0, column=2, sticky="w")
        ttk.Label(header, text="Startup").grid(row=0, column=3, sticky="w")
        ttk.Label(header, text="Actions").grid(row=0, column=4, sticky="w")

        # scrollable mapping list inside right column
        map_wrap = ttk.Frame(right)
        map_wrap.pack(fill=tk.BOTH, expand=True)
        self.map_canvas = tk.Canvas(map_wrap, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(map_wrap, orient="vertical", command=self.map_canvas.yview)
        self.map_inner = ttk.Frame(self.map_canvas)
        self.map_inner.bind("<Configure>", lambda e: self.map_canvas.configure(scrollregion=self.map_canvas.bbox("all")))
        self.map_canvas.create_window((0, 0), window=self.map_inner, anchor="nw")
        self.map_canvas.configure(yscrollcommand=vsb.set)
        self.map_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # bottom area: active mounts + logs + startup actions
        bottom = ttk.Frame(self, padding=pad)
        bottom.pack(fill=tk.BOTH)

        leftb = ttk.Frame(bottom)
        leftb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(leftb, text="Active mounts", font=(None, 11, "bold")).pack(anchor="w")
        self.lst_active = tk.Listbox(leftb, height=6)
        self.lst_active.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        midb = ttk.Frame(bottom)
        midb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 8))
        ttk.Label(midb, text="Console (last messages)", font=(None, 11, "bold")).pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(midb, height=6)
        self.txt_log.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.txt_log.configure(state=tk.DISABLED)

        rightb = ttk.Frame(bottom)
        rightb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(rightb, text="Startup (system)", font=(None, 11, "bold")).pack(anchor="w")
        sp = ttk.Frame(rightb)
        sp.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(sp, text="Add selected to startup", command=self.add_selected_to_startup).pack(side=tk.LEFT)
        ttk.Button(sp, text="Clear EZMount startups", command=self.clear_startups).pack(side=tk.LEFT, padx=(6, 0))
        self.lbl_startup = ttk.Label(rightb, text="Startup folder: " + str(get_startup_folder()))
        self.lbl_startup.pack(anchor="w", pady=(6, 0))

    # ---------- config load ----------
    def select_conf(self):
        p = filedialog.askopenfilename(title="Select rclone.conf", filetypes=[("conf", "*.conf"), ("All", "*.*")])
        if not p:
            return
        try:
            text = Path(p).read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}")
            return
        self.loaded_conf_path = p
        self.loaded_conf_text = text
        self.conf_sections = parse_conf_sections(text)

        self.txt_conf.configure(state="normal")
        self.txt_conf.delete("1.0", tk.END)
        self.txt_conf.insert(tk.END, text)
        self.txt_conf.configure(state="disabled")

        self.lbl_conf.config(text=Path(p).name)
        self.auto_generate_mappings()

    # ---------- mappings UI ----------
    def add_mapping_row(self, remote="new-remote:", label=None, drive="X:", startup=False):
        if label is None:
            label = remote
        idx = len(self.mappings)
        row = ttk.Frame(self.map_inner, padding=4)
        row.grid(row=idx, column=0, sticky="ew", pady=2)
        row.columnconfigure(0, weight=4)
        row.columnconfigure(1, weight=2)
        row.columnconfigure(2, weight=1)
        row.columnconfigure(3, weight=1)

        ent_remote = ttk.Entry(row)
        ent_remote.insert(0, remote)
        ent_remote.grid(row=0, column=0, sticky="ew", padx=4)

        ent_label = ttk.Entry(row)
        ent_label.insert(0, label)
        ent_label.grid(row=0, column=1, sticky="ew", padx=4)

        ent_drive = ttk.Entry(row, width=12)
        ent_drive.insert(0, drive)
        ent_drive.grid(row=0, column=2, sticky="ew", padx=4)

        var_startup = tk.BooleanVar(value=startup)
        chk = ttk.Checkbutton(row, variable=var_startup)
        chk.grid(row=0, column=3, sticky="w", padx=8)

        act_frame = ttk.Frame(row)
        act_frame.grid(row=0, column=4, sticky="e")
        ttk.Button(act_frame, text="Mount", command=lambda r=ent_remote, d=ent_drive: self._mount_single(r.get().strip(), d.get().strip())).pack(side=tk.LEFT)
        ttk.Button(act_frame, text="Unmount", command=lambda d=ent_drive: self._unmount_single(d.get().strip())).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(act_frame, text="Remove", command=lambda f=row: self._remove_mapping(f)).pack(side=tk.LEFT, padx=(6, 0))

        self.mappings.append(
            {
                "frame": row,
                "remote_widget": ent_remote,
                "label_widget": ent_label,
                "drive_widget": ent_drive,
                "startup_var": var_startup,
            }
        )

    def _remove_mapping(self, frame):
        for i, m in enumerate(list(self.mappings)):
            if m["frame"] == frame:
                m["frame"].destroy()
                self.mappings.pop(i)
                break
        for idx, mm in enumerate(self.mappings):
            mm["frame"].grid_configure(row=idx)

    def clear_mappings(self):
        if not self.mappings:
            return
        if not messagebox.askyesno("Clear mappings", "Clear all mappings?"):
            return
        for m in list(self.mappings):
            m["frame"].destroy()
        self.mappings.clear()

    # ---------- auto-generate ----------
    def auto_generate_mappings(self):
        for m in list(self.mappings):
            m["frame"].destroy()
        self.mappings.clear()

        if not self.conf_sections:
            return

        drive_ord = ord("X")
        for section, kv in self.conf_sections.items():
            type_val = kv.get("type", "").lower()
            bucket_val = kv.get("bucket") or kv.get("bucket_name")
            if type_val == "s3" or bucket_val:
                if bucket_val:
                    self.add_mapping_row(remote=f"{section}:{bucket_val}", label=f"{section}-{bucket_val}", drive=f"{chr(drive_ord)}:")
                    drive_ord = self._next_drive_ord(drive_ord)
                add_more = messagebox.askyesno("Additional buckets?", f"Remote '{section}' looks like S3 or has a bucket.\nAdd more buckets?")
                if add_more:
                    bucket_input = simpledialog.askstring("Buckets", f"Enter bucket names for '{section}' (comma-separated):")
                    if bucket_input:
                        for b in [x.strip() for x in bucket_input.split(",") if x.strip()]:
                            self.add_mapping_row(remote=f"{section}:{b}", label=f"{section}-{b}", drive=f"{chr(drive_ord)}:")
                            drive_ord = self._next_drive_ord(drive_ord)
                continue
            self.add_mapping_row(remote=f"{section}:", label=section, drive=f"{chr(drive_ord)}:")
            drive_ord = self._next_drive_ord(drive_ord)

    def _next_drive_ord(self, ord_val):
        ord_val -= 1
        if ord_val < ord("A"):
            ord_val = ord("Z")
        return ord_val

    # ---------- mount (detached) ----------
    def mount_all(self):
        if not self.rclone_path:
            messagebox.showerror("Missing rclone", "rclone not found on PATH")
            return
        to_mount = []
        for m in self.mappings:
            r = m["remote_widget"].get().strip()
            d = m["drive_widget"].get().strip()
            if not r:
                continue
            if self._is_drive_in_use(d):
                skip = messagebox.askyesno("Drive in use", f"{d} appears in use. Skip this mapping?")
                if skip:
                    continue
            to_mount.append((r, d))
        for r, d in to_mount:
            threading.Thread(target=self._start_detached_mount, args=(r, d), daemon=True).start()

    def _mount_single(self, remote, drive):
        if not self.rclone_path:
            messagebox.showerror("Missing rclone", "rclone not found on PATH")
            return
        if not remote:
            messagebox.showwarning("No remote", "Remote is empty")
            return
        threading.Thread(target=self._start_detached_mount, args=(remote, drive), daemon=True).start()

    def _start_detached_mount(self, remote, drive):
        if not self.rclone_path:
            self._log("rclone not found; cannot mount.")
            return
        cmd = [self.rclone_path, "mount", remote, drive, "--config", self.loaded_conf_path or "", "--vfs-cache-mode", "writes"]
        self._log(f"Starting (detached): {shlex.join(cmd)}")
        try:
            if os.name == "nt":
                creation = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creation |= subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "DETACHED_PROCESS"):
                    creation |= subprocess.DETACHED_PROCESS
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation)
            else:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp)
        except Exception as e:
            self._log(f"Failed to start detached mount {remote} -> {drive}: {e}")
            return

        mapping_text = f"{remote} -> {drive}"
        self.active_mounts.append({"mapping": mapping_text, "proc": proc, "started_at": time.time()})
        self._refresh_active_list()
        self._log(f"Mounted (detached): {mapping_text} (pid={proc.pid})")

    def _is_drive_in_use(self, d):
        if not d:
            return False
        if os.name == "nt" and len(d) >= 2 and d[1] == ":":
            return Path(d[0:2] + "\\").exists()
        return Path(d).exists()

    # ---------- unmount ----------
    def _unmount_single(self, drive):
        for am in list(self.active_mounts):
            if am["mapping"].endswith(f"-> {drive}") or drive in am["mapping"]:
                proc = am["proc"]
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                except Exception as e:
                    self._log(f"Error stopping pid {getattr(proc, 'pid', None)}: {e}")
                try:
                    self.active_mounts.remove(am)
                except ValueError:
                    pass
                self._refresh_active_list()
                self._log(f"Stopped mount {am['mapping']}")
                break

    def unmount_all(self):
        if not self.active_mounts:
            messagebox.showinfo("No mounts", "No active mounts")
            return
        if not messagebox.askyesno("Confirm", f"Stop {len(self.active_mounts)} mounts?"):
            return
        for am in list(self.active_mounts):
            try:
                proc = am["proc"]
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
            except Exception as e:
                self._log(f"Error stopping pid {getattr(proc, 'pid', None)}: {e}")
        self.active_mounts.clear()
        self._refresh_active_list()
        self._log("All mounts stopped")
        if os.name == "nt":
            if messagebox.askyesno("Restart Explorer?", "Restart Windows Explorer to refresh drive letters?"):
                try:
                    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=False)
                    time.sleep(0.4)
                    subprocess.Popen("start explorer.exe", shell=True)
                    self._log("Explorer restart requested")
                except Exception as e:
                    messagebox.showwarning("Explorer", f"Failed to restart explorer: {e}")

    # ---------- startup files (nircmd-aware) ----------
    def add_selected_to_startup(self):
        folder = ensure_startup_folder()
        if not folder:
            messagebox.showerror("Startup", "Could not determine startup folder")
            return
        entries = []
        for m in self.mappings:
            try:
                if m["startup_var"].get():
                    entries.append((m["remote_widget"].get().strip(), m["label_widget"].get().strip(), m["drive_widget"].get().strip()))
            except Exception:
                pass
        if not entries:
            messagebox.showinfo("No entries", "No mappings selected")
            return
        if not messagebox.askyesno("Create", f"Create {len(entries)} startup files in {folder}?"):
            return

        nircmd_path = shutil.which("nircmd")
        if not nircmd_path and self.rclone_path:
            maybe = Path(self.rclone_path).parent / "nircmd.exe"
            if maybe.exists():
                nircmd_path = str(maybe)

        created = 0
        for remote, label, drive in entries:
            try:
                safe_label = "".join(c for c in label if c.isalnum() or c in ("-", "_")).strip() or "mapping"
                if os.name == "nt":
                    fname = f"{STARTUP_PREFIX}{safe_label}.cmd"
                    fpath = folder / fname
                    if nircmd_path:
                        cmdline = f'"{nircmd_path}" exec hide "{self.rclone_path}" mount {shlex.quote(remote)} {shlex.quote(drive)} --config "{self.loaded_conf_path or ""}" --vfs-cache-mode writes --log-file "%TEMP%\\rclone_{safe_label}.log" --log-level INFO'
                    else:
                        cmdline = f'start "" /min "{self.rclone_path}" mount {shlex.quote(remote)} {shlex.quote(drive)} --config "{self.loaded_conf_path or ""}" --vfs-cache-mode writes --log-file "%TEMP%\\rclone_{safe_label}.log" --log-level INFO'
                    fpath.write_text(cmdline, encoding="utf-8")
                else:
                    fname = f"{STARTUP_PREFIX}{safe_label}.desktop"
                    fpath = folder / fname
                    content = (
                        "[Desktop Entry]\n"
                        "Type=Application\n"
                        f"Name={STARTUP_PREFIX}{safe_label}\n"
                        f'Exec=sh -c "nohup {shlex.quote(self.rclone_path)} mount {shlex.quote(remote)} {shlex.quote(drive)} --config \\"{self.loaded_conf_path or ""}\\" --vfs-cache-mode writes &> /dev/null &"\n'
                        "X-GNOME-Autostart-enabled=true\n"
                    )
                    fpath.write_text(content, encoding="utf-8")
                created += 1
            except Exception as e:
                self._log(f"Failed to create startup for {remote}: {e}")
        messagebox.showinfo("Created", f"Created {created} startup files in {folder}")

    def clear_startups(self):
        folder = get_startup_folder()
        if not folder or not folder.exists():
            messagebox.showinfo("None", "No startup folder found")
            return
        files = [p for p in folder.iterdir() if p.is_file() and p.name.startswith(STARTUP_PREFIX)]
        if not files:
            messagebox.showinfo("None", "No EZMount startup files")
            return
        if not messagebox.askyesno("Remove", f"Remove {len(files)} files from {folder}?"):
            return
        removed = 0
        for p in files:
            try:
                p.unlink()
                removed += 1
            except Exception as e:
                self._log(f"Failed to remove {p}: {e}")
        messagebox.showinfo("Removed", f"Removed {removed} files")

    # ---------- helpers ----------
    def _log(self, text):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n")
        txt = self.txt_log.get("1.0", "end")
        if len(txt) > LOG_MAX_CHARS:
            self.txt_log.delete("1.0", "end")
            self.txt_log.insert("end", txt[-LOG_MAX_CHARS:])
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _refresh_active_list(self):
        self.lst_active.delete(0, "end")
        for am in self.active_mounts:
            pid = getattr(am["proc"], "pid", "N/A")
            started = time.strftime("%H:%M:%S", time.localtime(am["started_at"]))
            self.lst_active.insert("end", f"{am['mapping']}  pid={pid}  started={started}")

    def _refresh_status_periodic(self):
        changed = False
        for am in list(self.active_mounts):
            if am["proc"].poll() is not None:
                try:
                    self.active_mounts.remove(am)
                except ValueError:
                    pass
                changed = True
        if changed:
            self._refresh_active_list()
        self.after(2000, self._refresh_status_periodic)


if __name__ == "__main__":
    app = EZMountApp()
    app.mainloop()
