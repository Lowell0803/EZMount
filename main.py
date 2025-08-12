#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
import subprocess, threading, shutil, os, time, shlex, json
import uuid
import webbrowser

import sv_ttk
import darkdetect

import subprocess, threading, shutil, os, time, shlex, json, uuid, webbrowser, sys

def resource_path(rel):
    """
    Return absolute path to a resource, works in dev and when PyInstaller bundles to _MEIPASS.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


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

def get_app_dir():
    if os.name == "nt":
        appdata = os.getenv("APPDATA") or str(Path.home())
        p = Path(appdata) / "EZMount"
    else:
        p = Path.home() / ".config" / "ezmount"
    p.mkdir(parents=True, exist_ok=True)
    return p

STARTUP_LOG_PATH = get_app_dir() / "startup_log.json"

def ensure_startup_folder():
    p = get_startup_folder()
    if p:
        p.mkdir(parents=True, exist_ok=True)
    return p

class EZMountApp(tk.Tk):
    def __init__(self):
        super().__init__()

        theme = (darkdetect.theme() or "Light").lower()
        sv_ttk.set_theme(theme)

        try:
            ico = resource_path("app.ico")
            if os.path.exists(ico):
                # self.iconbitmap(ico)
                pass
        except Exception:
            pass

        try:
            png = resource_path("app.png")
            if os.path.exists(png):
                img = tk.PhotoImage(file=png)
                pass
                # self.iconphoto(True, img)
        except Exception:
            pass

        active_theme = sv_ttk.get_theme() or theme
        style = ttk.Style()

        if active_theme.lower().startswith("dark"):
            self._bg_text = "#1c1c1c"
            self._fg_text = "#eaeaea"
            self._tree_bg = "#252525"
            self._tree_fg = "#eaeaea"
            self._canvas_bg = "#1a1a1a"
            self._entry_bg = "#2a2a2a"
        else:
            self._bg_text = "#ffffff"
            self._fg_text = "#111111"
            self._tree_bg = "#ffffff"
            self._tree_fg = "#111111"
            self._canvas_bg = "#ffffff"
            self._entry_bg = "#ffffff"

        try:
            style.configure("Treeview", background=self._tree_bg, fieldbackground=self._tree_bg, foreground=self._tree_fg)
            style.configure("Treeview.Heading", background=self._entry_bg, foreground=self._tree_fg)
        except Exception:
            pass

        self.title(f"{APP_TITLE} — rclone mount UI")
        self.geometry("1100x700")

        self.loaded_conf_path = None
        self.loaded_conf_text = ""
        self.conf_sections = {}

        self.mappings = []
        self.active_mounts = []

        self.rclone_path = shutil.which("rclone")
        self.startup_log = []

        self._build_ui()
        self._load_startup_log()
        self.after(300, self.scan_for_external_mounts)
        self.after(1000, self._refresh_status_periodic)

    def make_themed_text(self, parent, height=6, wrap=tk.NONE):
        frame = ttk.Frame(parent)
        text = tk.Text(frame, wrap=wrap, height=height, relief="flat", bd=0)

        try:
            text.configure(bg=self._bg_text, fg=self._fg_text, insertbackground=self._fg_text)
        except Exception:
            pass

        vs = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return frame, text

    def _build_ui(self):
        pad = 8

        toolbar = ttk.Frame(self, padding=(pad, pad // 2))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Select rclone.conf", command=self.select_conf).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Auto-generate mappings", command=self.auto_generate_mappings).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Add mapping", command=self.show_add_mapping_dialog).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear mappings", command=self.clear_mappings).pack(side=tk.LEFT, padx=6)
        ttk.Label(toolbar, text="    ").pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Mount All", command=self.mount_all).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Unmount All", command=self.unmount_all).pack(side=tk.RIGHT, padx=6)

        self.lbl_conf = ttk.Label(toolbar, text="(no config loaded)")
        self.lbl_conf.pack(side=tk.LEFT, padx=(12, 0))
        self.lbl_rclone = ttk.Label(toolbar, text=f"rclone: {self.rclone_path or '(not found)'}")
        self.lbl_rclone.pack(side=tk.LEFT, padx=(12, 0))

        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))

        left = ttk.Frame(main_frame, padding=pad)
        right = ttk.Frame(main_frame, padding=pad)
        left.place(relx=0.0, rely=0.0, relwidth=0.30, relheight=1.0)
        right.place(relx=0.30, rely=0.0, relwidth=0.70, relheight=1.0)

        ttk.Label(left, text="rclone.conf (read-only)", font=(None, 11, "bold")).pack(anchor="w")
        conf_frame, self.txt_conf = self.make_themed_text(left, wrap=tk.NONE, height=20)
        conf_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.txt_conf.configure(state="disabled")

        ttk.Label(right, text="Mappings", font=(None, 11, "bold")).pack(anchor="w")

        tree_container = ttk.Frame(right)
        tree_container.pack(fill=tk.BOTH, expand=True)

        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)
        tree_container.columnconfigure(1, weight=0, minsize=140)

        tree_frame = ttk.Frame(tree_container)
        tree_frame.grid(row=0, column=0, sticky="nsew")

        columns = ("remote", "label", "drive", "startup")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("remote", text="Remote[:path]")
        self.tree.heading("label", text="Label")
        self.tree.heading("drive", text="Drive / Mount")
        self.tree.heading("startup", text="Startup")
        self.tree.column("remote", anchor="w", width=360, stretch=True)
        self.tree.column("label", anchor="w", width=200, stretch=True)
        self.tree.column("drive", anchor="center", width=80, stretch=False)
        self.tree.column("startup", anchor="center", width=70, stretch=False)

        tree_vs = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_vs.pack(side="right", fill="y")

        actions_panel = ttk.Frame(tree_container, width=140)
        actions_panel.grid(row=0, column=1, sticky="ns", padx=(8,0))
        try:
            actions_panel.grid_propagate(False)
        except Exception:
            pass

        ttk.Button(actions_panel, text="Mount", command=self.action_mount_selected).pack(fill="x", pady=(0,6))
        ttk.Button(actions_panel, text="Unmount", command=self.action_unmount_selected).pack(fill="x", pady=(0,6))
        ttk.Button(actions_panel, text="Toggle Startup", command=self.action_toggle_startup).pack(fill="x", pady=(0,6))
        ttk.Button(actions_panel, text="Remove", command=self.action_remove_selected).pack(fill="x", pady=(0,6))
        ttk.Button(actions_panel, text="Add...", command=self.show_add_mapping_dialog).pack(fill="x", pady=(0,6))
        ttk.Button(actions_panel, text="Donate", command=lambda: webbrowser.open("https://buymeacoffee.com/yvanlowellaquino")).pack(fill="x", pady=(0,6))
        

        self.tree.bind("<Double-1>", self._on_tree_double_click)

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
        log_frame, self.txt_log = self.make_themed_text(midb, height=6)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.txt_log.configure(state="disabled")

        rightb = ttk.Frame(bottom)
        rightb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(rightb, text="Startup (system)", font=(None, 11, "bold")).pack(anchor="w")
        sp = ttk.Frame(rightb)
        sp.pack(pady=(6, 0))
        ttk.Button(sp, text="Add selected to startup", command=self.add_selected_to_startup).pack(side=tk.LEFT)
        ttk.Button(sp, text="Clear EZMount startups", command=self.clear_startups).pack(side=tk.LEFT, padx=(6, 0))
        self.lbl_startup = ttk.Label(rightb, text="Startup folder: " + str(get_startup_folder()))
        self.lbl_startup.pack(anchor="w", pady=(6, 0))
        ttk.Button(rightb, text="Open startup folder", command=self.open_startup_folder).pack(side=tk.BOTTOM, pady=(6, 0))

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
        self.scan_for_external_mounts()

    # ---------- mappings (treeview) ----------
    def _new_iid(self):
        return str(uuid.uuid4())

    def add_mapping_row(self, remote="new-remote:", label=None, drive="X:", startup=False, select=False):
        if label is None:
            label = remote
        iid = self._new_iid()
        m = {"id": iid, "remote": remote, "label": label, "drive": drive, "startup": bool(startup)}
        self.mappings.append(m)
        startup_text = "Yes" if m["startup"] else ""
        self.tree.insert("", "end", iid, values=(m["remote"], m["label"], m["drive"], startup_text))
        if select:
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _find_mapping_by_iid(self, iid):
        for m in self.mappings:
            if m["id"] == iid:
                return m
        return None

    def _remove_mapping_by_iid(self, iid):
        m = self._find_mapping_by_iid(iid)
        if m:
            try:
                self.mappings.remove(m)
            except Exception:
                pass
        try:
            self.tree.delete(iid)
        except Exception:
            pass

    def clear_mappings(self):
        if not self.mappings:
            return
        if not messagebox.askyesno("Clear mappings", "Clear all mappings?"):
            return
        self.mappings.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def auto_generate_mappings(self):
        self.clear_mappings()
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

    def _on_tree_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not row or not column:
            return
        col_index = int(column.replace("#", "")) - 1
        col_key = ("remote", "label", "drive", "startup")[col_index]
        bbox = self.tree.bbox(row, column)
        if not bbox:
            return
        x, y, w, h = bbox
        edit_value = self.tree.set(row, column)
        entry = ttk.Entry(self.tree)
        entry.insert(0, edit_value)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        def commit(event=None):
            new = entry.get().strip()
            entry.destroy()
            if col_key == "startup":
                new_bool = bool(new and new.lower() not in ("", "no", "false", "0"))
                m = self._find_mapping_by_iid(row)
                if m:
                    m["startup"] = new_bool
                    self.tree.set(row, column, "Yes" if new_bool else "")
            else:
                self.tree.set(row, column, new)
                m = self._find_mapping_by_iid(row)
                if m:
                    m[col_key] = new
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)

    def _get_selected_mapping(self):
        sel = self.tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        m = self._find_mapping_by_iid(iid)
        return iid, m

    def action_mount_selected(self):
        iid, m = self._get_selected_mapping()
        if not m:
            messagebox.showinfo("Select", "Select a mapping first")
            return
        self._mount_single(m["remote"], m["drive"])

    def action_unmount_selected(self):
        iid, m = self._get_selected_mapping()
        if not m:
            messagebox.showinfo("Select", "Select a mapping first")
            return
        self._unmount_single(m["drive"])

    def action_toggle_startup(self):
        iid, m = self._get_selected_mapping()
        if not m:
            messagebox.showinfo("Select", "Select a mapping first")
            return
        m["startup"] = not m["startup"]
        self.tree.set(iid, "startup", "Yes" if m["startup"] else "")

    def action_remove_selected(self):
        iid, m = self._get_selected_mapping()
        if not m:
            messagebox.showinfo("Select", "Select a mapping first")
            return
        if not messagebox.askyesno("Remove", f"Remove mapping '{m['label']}'?"):
            return
        self._remove_mapping_by_iid(iid)

    def show_add_mapping_dialog(self):
        remote = simpledialog.askstring("Remote", "Remote (eg. remote:bucket):", parent=self)
        if remote is None:
            return
        label = simpledialog.askstring("Label", "Label (optional):", parent=self) or remote
        drive = simpledialog.askstring("Drive", "Drive (eg. X: or /mnt/point):", parent=self) or "X:"
        startup_ans = messagebox.askyesno("Startup", "Add to startup by default?")
        self.add_mapping_row(remote=remote.strip(), label=label.strip(), drive=drive.strip(), startup=startup_ans, select=True)

    # ---------- mount (detached) ----------
    def mount_all(self):
        if not self.rclone_path:
            messagebox.showerror("Missing rclone", "rclone not found on PATH")
            return
        to_mount = []
        for m in self.mappings:
            r = m["remote"].strip()
            d = m["drive"].strip()
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
        self.active_mounts.append({"mapping": mapping_text, "proc": proc, "started_at": time.time(), "detected": False})
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
        if not drive:
            messagebox.showinfo("No drive", "No drive specified")
            return
        found = False
        for am in list(self.active_mounts):
            if am["mapping"].endswith(f"-> {drive}") or drive in am["mapping"]:
                found = True
                proc = am.get("proc")
                if proc:
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
                else:
                    do_it = messagebox.askyesno("External mount", f"This mount ({am['mapping']}) wasn't started by EZMount.\nTry to unmount/stop it anyway?")
                    if not do_it:
                        return
                    self._log(f"Attempting to unmount external mount: {am['mapping']}")
                    if os.name == "nt":
                        try:
                            subprocess.run(["taskkill", "/f", "/im", "rclone.exe"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            self._log("Requested taskkill for rclone.exe (Windows).")
                        except Exception as e:
                            self._log(f"Failed to taskkill rclone.exe: {e}")
                    else:
                        try:
                            subprocess.run(["fusermount", "-u", drive], check=False)
                            self._log(f"Ran fusermount -u {drive}")
                        except Exception:
                            try:
                                subprocess.run(["umount", drive], check=False)
                                self._log(f"Ran umount {drive}")
                            except Exception as e:
                                self._log(f"Failed to unmount {drive}: {e}")
                    try:
                        self.active_mounts.remove(am)
                    except ValueError:
                        pass
                    self._refresh_active_list()
                break
        if not found:
            messagebox.showinfo("Not found", f"No active mount matching {drive}")

    def unmount_all(self):
        if not self.active_mounts:
            messagebox.showinfo("No mounts", "No active mounts")
            return
        if not messagebox.askyesno("Confirm", f"Stop {len(self.active_mounts)} mounts?"):
            return
        for am in list(self.active_mounts):
            try:
                proc = am.get("proc")
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                else:
                    if os.name == "nt":
                        try:
                            subprocess.run(["taskkill", "/f", "/im", "rclone.exe"], check=False)
                            self._log("Requested taskkill for rclone.exe (Windows).")
                        except Exception as e:
                            self._log(f"Error stopping external rclone processes: {e}")
                    else:
                        drive = am["mapping"].split("->")[-1].strip()
                        try:
                            subprocess.run(["fusermount", "-u", drive], check=False)
                        except Exception:
                            try:
                                subprocess.run(["umount", drive], check=False)
                            except Exception as e:
                                self._log(f"Failed to unmount {drive}: {e}")
            except Exception as e:
                self._log(f"Error stopping pid {getattr(am.get('proc'), 'pid', None)}: {e}")
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

    # ---------- startup files (nircmd-aware) + startup log handling ----------
    def add_selected_to_startup(self):
        folder = ensure_startup_folder()
        if not folder:
            messagebox.showerror("Startup", "Could not determine startup folder")
            return
        entries = []
        for m in self.mappings:
            if m.get("startup"):
                entries.append((m["remote"], m["label"], m["drive"]))
        if not entries:
            messagebox.showinfo("No entries", "No mappings selected for startup")
            return
        if not messagebox.askyesno("Create", f"Create {len(entries)} startup files in {folder}?"):
            return

        log_entries = []
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
                log_entries.append({
                    "label": safe_label,
                    "remote": remote,
                    "drive": drive,
                    "filename": str(fpath),
                    "created_at": int(time.time()),
                    "cmdline": cmdline if 'cmdline' in locals() else ""
                })
            except Exception as e:
                self._log(f"Failed to create startup for {remote}: {e}")

        try:
            STARTUP_LOG_PATH.write_text(json.dumps(log_entries, indent=2), encoding="utf-8")
            self.startup_log = log_entries
            self._log(f"Wrote startup log with {len(log_entries)} entries to {STARTUP_LOG_PATH}")
        except Exception as e:
            self._log(f"Failed to write startup log: {e}")

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
        try:
            if STARTUP_LOG_PATH.exists():
                STARTUP_LOG_PATH.unlink()
                self.startup_log = []
        except Exception:
            pass
        messagebox.showinfo("Removed", f"Removed {removed} files and cleared startup log")

    def open_startup_folder(self):
        folder = get_startup_folder()
        if not folder or not folder.exists():
            messagebox.showinfo("No startup folder", "Startup folder not found")
            return
        try:
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showwarning("Open folder", f"Failed to open folder: {e}")

    def _load_startup_log(self):
        try:
            if STARTUP_LOG_PATH.exists():
                self.startup_log = json.loads(STARTUP_LOG_PATH.read_text(encoding="utf-8") or "[]")
                self._log(f"Loaded startup log ({len(self.startup_log)} entries) from {STARTUP_LOG_PATH}")
            else:
                self.startup_log = []
        except Exception as e:
            self._log(f"Failed to load startup log: {e}")
            self.startup_log = []

    def _log(self, text):
        try:
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", text + "\n")
            txt = self.txt_log.get("1.0", "end")
            if len(txt) > LOG_MAX_CHARS:
                self.txt_log.delete("1.0", "end")
                self.txt_log.insert("end", txt[-LOG_MAX_CHARS:])
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        except Exception:
            pass

    def _refresh_active_list(self):
        self.lst_active.delete(0, "end")
        for am in self.active_mounts:
            pid = getattr(am["proc"], "pid", "N/A") if am.get("proc") else "N/A"
            started = time.strftime("%H:%M:%S", time.localtime(am["started_at"])) if am.get("started_at") else "-"
            det = " (detected)" if am.get("detected") else ""
            src = " [startup]" if am.get("from_startup_log") else ""
            self.lst_active.insert("end", f"{am['mapping']}  pid={pid}  started={started}{det}{src}")

    def _refresh_status_periodic(self):
        changed = False
        for am in list(self.active_mounts):
            if am.get("proc") and am["proc"].poll() is not None:
                try:
                    self.active_mounts.remove(am)
                except ValueError:
                    pass
                changed = True
        self.scan_for_external_mounts()
        if changed:
            self._refresh_active_list()
        self.after(2000, self._refresh_status_periodic)

    def scan_for_external_mounts(self):
        detected_now = []
        for m in self.mappings:
            d = m.get("drive", "").strip()
            if not d:
                continue
            if self._is_drive_in_use(d):
                mapping_text = f"{m.get('remote','').strip()} -> {d}"
                if not any(am["mapping"] == mapping_text for am in self.active_mounts):
                    self.active_mounts.append({"mapping": mapping_text, "proc": None, "started_at": time.time(), "detected": True, "from_startup_log": False})
                    self._log(f"Detected external mount (from mappings): {mapping_text}")
                detected_now.append(mapping_text)

        for entry in self.startup_log:
            drive = entry.get("drive")
            remote = entry.get("remote") or ""
            label = entry.get("label") or ""
            if not drive:
                continue
            if self._is_drive_in_use(drive):
                mapping_text = f"{remote} -> {drive}" if remote else f"{label} -> {drive}"
                if not any(am["mapping"] == mapping_text for am in self.active_mounts):
                    self.active_mounts.append({"mapping": mapping_text, "proc": None, "started_at": time.time(), "detected": True, "from_startup_log": True})
                    self._log(f"Detected external mount (from startup log): {mapping_text}")
                detected_now.append(mapping_text)

        removed = []
        for am in list(self.active_mounts):
            if am.get("detected"):
                if am["mapping"] not in detected_now:
                    try:
                        self.active_mounts.remove(am)
                        removed.append(am["mapping"])
                    except ValueError:
                        pass
        if removed:
            self._log(f"Removed stale detected mounts: {removed}")
        self._refresh_active_list()

if __name__ == "__main__":
    app = EZMountApp()
    app.mainloop()
