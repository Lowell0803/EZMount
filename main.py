"""
EZMount — Full working preview + basic mount/unmount using rclone.

Features:
- Load an rclone.conf (supports reading encrypted file contents; passing password to rclone isn't guaranteed).
- Parses remotes from the config and offers to auto-generate mappings.
- Detects S3-style remotes and asks for multiple buckets when needed.
- Lets you add/remove/edit mappings: remote (remote[:path]), label, drive letter / mount point.
- Checks if a Windows drive letter (e.g. X:) is already in use.
- Starts `rclone mount` processes (runs them in background) and tracks processes so you can "Unmount All".

Notes / caveats:
- This app expects `rclone` to be installed and available on PATH. If rclone is missing it will warn you.
- Encrypted rclone configs: rclone may prompt for a password when it needs to decrypt the config. The app attempts to pass the provided password on stdin when launching rclone, but behavior depends on rclone versions and how the config was encrypted.
- Mount behavior differs across OS. This app is aimed mainly at Windows-style drive letters, but it will work on Linux/macOS by using mount points (directories) as the "drive" field.
- Killing the rclone process is used to unmount. On some platforms you may need admin privileges or fusermount/umount calls.

Run: `python ezmount_app.py`
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext
from pathlib import Path
import subprocess
import threading
import shutil
import os
import sys
import time

# ---------- Utilities to parse rclone.conf ----------

def parse_conf_sections(conf_text: str):
    """Return dict of section -> dict of key: value lines inside that section."""
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


def parse_remotes_from_conf(conf_text: str):
    return list(parse_conf_sections(conf_text).keys())


def conf_basename(path):
    try:
        return Path(path).name
    except Exception:
        return "(none)"

# ---------- Main application ----------

class EZMountApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EZMount — rclone UI")
        self.geometry("1100x700")

        self.loaded_conf_path = None
        self.loaded_conf_text = ""
        self.conf_sections = {}

        # mapping rows: list of dicts with widgets
        self.mappings = []

        # active mounts: list of dicts {mapping, process, started_at}
        self.active_mounts = []

        self.rclone_path = shutil.which("rclone")

        self._build_ui()

    def _build_ui(self):
        pad = 8
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=pad, pady=pad)

        ttk.Button(top, text="Select rclone.conf...", command=self.select_conf).pack(side=tk.LEFT)
        ttk.Button(top, text="Show rclone path", command=self._show_rclone_path).pack(side=tk.LEFT, padx=(6,0))
        ttk.Label(top, text=" ").pack(side=tk.LEFT, padx=6)
        ttk.Label(top, text="Config password (if encrypted):").pack(side=tk.LEFT)
        self.var_password = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_password, show="*", width=30).pack(side=tk.LEFT, padx=(6,0))

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0,pad))

        # left: conf viewer
        left = ttk.Frame(main)
        main.add(left, weight=1)

        ttk.Label(left, text="rclone.conf (read-only):").pack(anchor="w")
        self.txt_conf = scrolledtext.ScrolledText(left, wrap=tk.NONE, height=20)
        self.txt_conf.pack(fill=tk.BOTH, expand=True)
        self.txt_conf.configure(state=tk.DISABLED)

        # right: mappings and controls
        right = ttk.Frame(main)
        main.add(right, weight=1)

        hdr = ttk.Label(right, text="Mappings", font=(None, 11, "bold"))
        hdr.pack(anchor="w")

        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.map_canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.map_canvas.yview)
        self.map_inner = ttk.Frame(self.map_canvas)
        self.map_inner.bind("<Configure>", lambda e: self.map_canvas.configure(scrollregion=self.map_canvas.bbox("all")))
        self.map_canvas.create_window((0,0), window=self.map_inner, anchor="nw")
        self.map_canvas.configure(yscrollcommand=vsb.set)
        self.map_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # header row
        hr = ttk.Frame(self.map_inner)
        hr.grid(row=0, column=0, sticky="ew", pady=(0,6))
        ttk.Label(hr, text="Remote[:path]", width=36).grid(row=0, column=0, padx=2)
        ttk.Label(hr, text="Label", width=22).grid(row=0, column=1, padx=2)
        ttk.Label(hr, text="Drive/Mount", width=14).grid(row=0, column=2, padx=2)
        ttk.Label(hr, text="", width=10).grid(row=0, column=3, padx=2)

        controls = ttk.Frame(right)
        controls.pack(fill=tk.X, pady=(6,0))
        ttk.Button(controls, text="Auto-generate mappings from conf", command=self.auto_generate_mappings).pack(side=tk.LEFT)
        ttk.Button(controls, text="Add mapping", command=self.add_mapping_row).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(controls, text="Clear mappings", command=self.clear_mappings).pack(side=tk.LEFT, padx=(6,0))

        ttk.Button(controls, text="Mount All", command=self.mount_all).pack(side=tk.RIGHT)
        ttk.Button(controls, text="Unmount All", command=self.unmount_all).pack(side=tk.RIGHT, padx=(6,0))

        # bottom: active mounts and logs
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.BOTH, expand=False, padx=pad, pady=pad)

        leftbot = ttk.Frame(bottom)
        leftbot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(leftbot, text="Active mounts:").pack(anchor="w")
        self.lst_active = tk.Listbox(leftbot, height=6)
        self.lst_active.pack(fill=tk.BOTH, expand=True)

        rightbot = ttk.Frame(bottom)
        rightbot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6,0))
        ttk.Label(rightbot, text="Console output (last lines):").pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(rightbot, height=6)
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.txt_log.configure(state=tk.DISABLED)

    def _show_rclone_path(self):
        if self.rclone_path:
            messagebox.showinfo("rclone", f"rclone found: {self.rclone_path}")
        else:
            messagebox.showwarning("rclone", "rclone not found on PATH. Please install rclone and ensure it's on PATH.")

    # ---------- conf load ----------
    def select_conf(self):
        p = filedialog.askopenfilename(title="Select rclone.conf", filetypes=[("conf","*.conf"), ("All","*.*")])
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
        self.txt_conf.configure(state=tk.NORMAL)
        self.txt_conf.delete("1.0", tk.END)
        self.txt_conf.insert(tk.END, text)
        self.txt_conf.configure(state=tk.DISABLED)

        # auto-generate mappings immediately
        self.auto_generate_mappings()

    # ---------- mapping rows ----------
    def add_mapping_row(self, remote="new-remote:", label=None, drive="X:"):
        if label is None:
            label = remote
        row = len(self.mappings) + 1
        frame = ttk.Frame(self.map_inner)
        frame.grid(row=row, column=0, sticky="ew", pady=3)
        frame.columnconfigure(0, weight=1)

        ent_remote = ttk.Entry(frame, width=40)
        ent_remote.insert(0, remote)
        ent_remote.grid(row=0, column=0, padx=2)

        ent_label = ttk.Entry(frame, width=20)
        ent_label.insert(0, label)
        ent_label.grid(row=0, column=1, padx=2)

        ent_drive = ttk.Entry(frame, width=10)
        ent_drive.insert(0, drive)
        ent_drive.grid(row=0, column=2, padx=2)

        btn_rm = ttk.Button(frame, text="Remove", width=10, command=lambda f=frame: self._remove_mapping(f))
        btn_rm.grid(row=0, column=3, padx=6)

        self.mappings.append({
            'frame': frame,
            'remote_widget': ent_remote,
            'label_widget': ent_label,
            'drive_widget': ent_drive
        })

    def _remove_mapping(self, frame):
        for i, m in enumerate(list(self.mappings)):
            if m['frame'] == frame:
                m['frame'].destroy()
                self.mappings.pop(i)
                break

    def clear_mappings(self):
        if not self.mappings:
            return
        if not messagebox.askyesno("Clear mappings", "Clear all mappings?"):
            return
        for m in list(self.mappings):
            m['frame'].destroy()
        self.mappings.clear()

    # ---------- auto-generate mappings ----------
    def auto_generate_mappings(self):
        # clear existing mappings
        for m in list(self.mappings):
            m['frame'].destroy()
        self.mappings.clear()

        if not self.conf_sections:
            messagebox.showinfo("No config", "Load an rclone.conf first.")
            return

        drive_ord = ord('X')
        for section, kv in self.conf_sections.items():
            type_val = kv.get('type', '').lower()
            bucket_val = kv.get('bucket') or kv.get('bucket_name')

            # If it's s3 or has an explicit bucket
            if type_val == 's3' or bucket_val:
                # Build default entry for existing bucket key if present
                if bucket_val:
                    remote_spec = f"{section}:{bucket_val}"
                    self.add_mapping_row(remote=remote_spec, label=f"{section}-{bucket_val}", drive=f"{chr(drive_ord)}:")
                    drive_ord = self._next_drive_ord(drive_ord)

                # Ask if user wants to add more buckets for this remote (comma-separated)
                add_more = messagebox.askyesno("Additional buckets?", f"Remote '{section}' looks like S3 or has a bucket.\nDo you want to add additional buckets for this remote?")
                if add_more:
                    bucket_input = simpledialog.askstring("Enter buckets", f"Enter bucket names for '{section}' (comma-separated):")
                    if bucket_input:
                        buckets = [b.strip() for b in bucket_input.split(",") if b.strip()]
                        for b in buckets:
                            remote_spec = f"{section}:{b}"
                            self.add_mapping_row(remote=remote_spec, label=f"{section}-{b}", drive=f"{chr(drive_ord)}:")
                            drive_ord = self._next_drive_ord(drive_ord)
                continue

            # Default single mapping for this remote
            remote_spec = f"{section}:"
            self.add_mapping_row(remote=remote_spec, label=section, drive=f"{chr(drive_ord)}:")
            drive_ord = self._next_drive_ord(drive_ord)

    def _next_drive_ord(self, ord_val):
        ord_val -= 1
        if ord_val < ord('A'):
            ord_val = ord('Z')
        return ord_val

    # ---------- mounting logic ----------
    def mount_all(self):
        if not self.rclone_path:
            messagebox.showerror("Missing rclone", "rclone executable not found on PATH. Install rclone first.")
            return
        if not self.mappings:
            messagebox.showinfo("No mappings", "No mappings defined — nothing to mount.")
            return

        # For each mapping, check drive availability
        to_mount = []
        for m in self.mappings:
            remote = m['remote_widget'].get().strip()
            label = m['label_widget'].get().strip()
            drive = m['drive_widget'].get().strip()
            if not remote:
                continue
            if self._is_drive_in_use(drive):
                if not messagebox.askyesno("Drive in use", f"Drive {drive} appears to be in use.\nSkip this mapping? Press No to attempt anyway."):
                    to_mount.append((remote, label, drive))
            else:
                to_mount.append((remote, label, drive))

        if not to_mount:
            return

        # Start mounts in separate threads so UI doesn't block
        for remote, label, drive in to_mount:
            t = threading.Thread(target=self._start_mount_process, args=(remote, label, drive), daemon=True)
            t.start()

    def _is_drive_in_use(self, drive_str: str) -> bool:
        # Windows drive letter check: X: or X:\
        # On UNIX, treat drive_str as path
        if os.name == 'nt':
            d = drive_str.replace('/', '').replace('\\', '')
            if len(d) == 2 and d[1] == ':':
                path = d + "\\"
                return Path(path).exists()
            # fallback
            return Path(drive_str).exists()
        else:
            return Path(drive_str).exists()

    def _start_mount_process(self, remote: str, label: str, drive: str):
        # Build rclone mount command
        # On Windows use drive letter e.g. X:
        # On POSIX, drive should be a directory
        cmd = [self.rclone_path, 'mount', remote, drive, '--config', self.loaded_conf_path, '--vfs-cache-mode', 'writes']

        # Add a label as a tag in --attr or --volname for some backends? We'll skip fancy flags.

        # Start process detached so it doesn't block; capture stdout/stderr
        try:
            creationflags = 0
            stdin = subprocess.PIPE
            if os.name == 'nt':
                # Windows: create new process group
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=stdin, creationflags=creationflags)
        except Exception as e:
            self._log(f"Failed to start mount for {remote} -> {drive}: {e}")
            return

        self.active_mounts.append({'mapping': f"{remote} -> {drive}", 'process': proc, 'started_at': time.time()})
        self._refresh_active_list()

        # If user provided a password, try sending it to stdin (may or may not be used by rclone)
        if self.var_password.get():
            try:
                pw = (self.var_password.get() + "\n").encode('utf-8')
                proc.stdin.write(pw)
                proc.stdin.flush()
            except Exception:
                pass

        # Read output lines and display last N lines in the console area
        try:
            for raw in proc.stdout:
                try:
                    line = raw.decode('utf-8', errors='replace')
                except Exception:
                    line = str(raw)
                self._log(line.strip())
        except Exception as e:
            self._log(f"Mount process ended for {remote} -> {drive}: {e}")
        finally:
            # Process exited
            self._log(f"Mount process exited for {remote} -> {drive}")
            # remove from active_mounts
            self.active_mounts = [am for am in self.active_mounts if am['process'] != proc]
            self._refresh_active_list()

    def _log(self, text: str):
        # append to console with limit
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, text + "\n")
        # keep only last 2000 chars
        content = self.txt_log.get('1.0', tk.END)
        if len(content) > 20000:
            self.txt_log.delete('1.0', tk.END)
            self.txt_log.insert(tk.END, content[-20000:])
        self.txt_log.see(tk.END)
        self.txt_log.configure(state=tk.DISABLED)

    def _refresh_active_list(self):
        self.lst_active.delete(0, tk.END)
        for am in self.active_mounts:
            started = time.strftime('%H:%M:%S', time.localtime(am['started_at']))
            pid = am['process'].pid if am['process'] else 'N/A'
            self.lst_active.insert(tk.END, f"{am['mapping']}  (pid={pid})  started={started}")

    def unmount_all(self):
        if not self.active_mounts:
            messagebox.showinfo("No mounts", "No active mounts to unmount.")
            return
        if not messagebox.askyesno("Unmount all", f"Stop {len(self.active_mounts)} rclone mount processes?"):
            return
        # Terminate processes
        for am in list(self.active_mounts):
            proc = am['process']
            try:
                proc.terminate()
                # Wait briefly; if still alive kill
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
            except Exception as e:
                self._log(f"Error stopping pid {getattr(proc,'pid',None)}: {e}")
        # Clear list
        self.active_mounts.clear()
        self._refresh_active_list()
        self._log("All mounts stopped by user.")


if __name__ == '__main__':
    app = EZMountApp()
    app.mainloop()
