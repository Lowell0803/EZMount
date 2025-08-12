import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from logic import APP_TITLE, KOFI_URL, STARTUP_PREFIX, parse_remotes_from_conf, conf_basename
import webbrowser

class EZMountUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE + " — Preview")
        self.geometry("980x640")
        self.minsize(820, 520)

        self.loaded_conf_path = None
        self.loaded_conf_text = ""
        self.mappings = []
        self.simulated_startups = []

        self._build_notebook()
        self._build_footer()

    def _build_notebook(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.nb = nb

        self.tab_config = ttk.Frame(nb)
        nb.add(self.tab_config, text="Config & Mappings")
        self._build_tab_config(self.tab_config)

        self.tab_startup = ttk.Frame(nb)
        nb.add(self.tab_startup, text="Startup / Info")
        self._build_tab_startup(self.tab_startup)

    def _build_tab_config(self, parent):
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=tk.X, padx=8, pady=(8, 6))

        btn_select = ttk.Button(top_frame, text="Select rclone.conf...", command=self._select_conf_file)
        btn_select.pack(side=tk.LEFT)

        lbl_pw = ttk.Label(top_frame, text="Config password (if encrypted):")
        lbl_pw.pack(side=tk.LEFT, padx=(16,6))

        self.var_password = tk.StringVar()
        ent_pw = ttk.Entry(top_frame, textvariable=self.var_password, show="*", width=30)
        ent_pw.pack(side=tk.LEFT)

        mid = ttk.Frame(parent)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # --- Left and right panes: make them both expand equally so they take ~50/50 ---
        left = ttk.Frame(mid)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))

        right = ttk.Frame(mid)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6,0))

        # LEFT: read-only conf view
        lbl_conf = ttk.Label(left, text="rclone.conf (read-only):")
        lbl_conf.pack(anchor="w")
        self.txt_conf = scrolledtext.ScrolledText(left, wrap=tk.NONE, height=18)
        self.txt_conf.pack(fill=tk.BOTH, expand=True)
        self.txt_conf.configure(state=tk.DISABLED)

        # RIGHT: mappings area (keeps original widths/behavior inside)
        hdr = ttk.Label(right, text="Mappings (editable): remote -> label + drive letter", font=("Segoe UI", 10, "bold"))
        hdr.pack(anchor="w", pady=(0,6))

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

        hdr_row = ttk.Frame(self.map_inner)
        hdr_row.grid(row=0, column=0, sticky="ew", pady=(0,6))
        ttk.Label(hdr_row, text="Remote", width=28).grid(row=0, column=0, padx=2)
        ttk.Label(hdr_row, text="Label", width=22).grid(row=0, column=1, padx=2)
        ttk.Label(hdr_row, text="Drive Letter", width=12).grid(row=0, column=2, padx=2)
        ttk.Label(hdr_row, text="", width=8).grid(row=0, column=3, padx=2)

        bottom = ttk.Frame(right)
        bottom.pack(fill=tk.X, pady=(6,0))

        # renamed button text -> "Load mappings"
        btn_auto = ttk.Button(bottom, text="Load mappings", command=self._auto_generate_mappings)
        btn_auto.pack(side=tk.LEFT)

        # removed Add mapping button per request (no btn_add)

        btn_clear = ttk.Button(bottom, text="Clear mappings", command=self._clear_mappings)
        btn_clear.pack(side=tk.LEFT, padx=(6,0))

        btn_mount = ttk.Button(bottom, text="Mount All", command=self._mock_mount_all)
        btn_mount.pack(side=tk.RIGHT, padx=(6,0))

        btn_unmount = ttk.Button(bottom, text="Unmount All", command=self._mock_unmount_all)
        btn_unmount.pack(side=tk.RIGHT)

    def _build_tab_startup(self, parent):
        pad = 8
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        lbl = ttk.Label(frm, text="Startup actions (preview-only)", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w", pady=(0,6))

        btn_run_startup = ttk.Button(frm, text="Run on startup using this .conf", command=self._create_startup_for_conf)
        btn_run_startup.pack(anchor="w", pady=(0,6))

        btn_clean = ttk.Button(frm, text="Clear EZMount Startups", command=self._clear_ezmount_startups)
        btn_clean.pack(anchor="w", pady=(0,6))

        lbl2 = ttk.Label(frm, text="Simulated startup entries (prefix: " + STARTUP_PREFIX + "):")
        lbl2.pack(anchor="w", pady=(6,0))

        self.lst_startups = tk.Listbox(frm, height=8)
        self.lst_startups.pack(fill=tk.X, pady=(4,8))

        info_frame = ttk.LabelFrame(frm, text="EZMount")
        info_frame.pack(fill=tk.BOTH, expand=True, pady=(8,0))

        about_text = (
            "EZMount — preview UI\n\n"
            "Workflow:\n"
            "1) User selects their own rclone.conf (the UI only reads it).\n"
            "2) (If encrypted) user types the config password in the password box above.\n"
            "3) Auto-generate mappings creates editable rows mapping remote -> label + drive.\n"
            "4) Mount All / Unmount All are available (preview-only here).\n\n"
            "Startup buttons below will simulate creating/removing startup entries with prefix '" + STARTUP_PREFIX + "'."
        )
        ttk.Label(info_frame, text=about_text, justify="left").pack(fill=tk.BOTH, padx=8, pady=6)

        support_frame = ttk.Frame(frm)
        support_frame.pack(fill=tk.X, pady=(6,0))
        ttk.Button(support_frame, text="Support me (Ko-fi)", command=lambda: webbrowser.open_new_tab(KOFI_URL)).pack(side=tk.LEFT)
        ttk.Button(support_frame, text="About me", command=self._show_about).pack(side=tk.LEFT, padx=(6,0))

    def _build_footer(self):
        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, padx=10, pady=(0,8))
        ttk.Label(footer, text="EZMount — UI-only preview. Nothing is written/run.").pack(side=tk.LEFT)

    # ----- Actions (unchanged) -----
    def _select_conf_file(self):
        p = filedialog.askopenfilename(title="Select rclone.conf", filetypes=[("conf","*.conf"), ("All","*.*")])
        if not p:
            return
        try:
            text = Path(p).read_text(encoding="utf-8")
            self.loaded_conf_path = p
            self.loaded_conf_text = text
            self.txt_conf.configure(state=tk.NORMAL)
            self.txt_conf.delete("1.0", tk.END)
            self.txt_conf.insert(tk.END, text)
            self.txt_conf.configure(state=tk.DISABLED)
            messagebox.showinfo("Loaded (preview)", f"Loaded (preview-only): {p}\n\n"
                                "If your config is encrypted, enter the password in the password box before mounting.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}")

    def _auto_generate_mappings(self):
        if not self.loaded_conf_text:
            messagebox.showwarning("No config", "Load an rclone.conf first.")
            return
        remotes = parse_remotes_from_conf(self.loaded_conf_text)
        if not remotes:
            messagebox.showinfo("No remotes", "No remotes detected in the loaded config (preview parser).")
            return
        existing = {m['remote_widget'].get() for m in self.mappings}
        drive_ord = ord('X')
        for r in remotes:
            if r in existing:
                continue
            drive_letter = f"{chr(drive_ord)}:"
            drive_ord += 1
            if drive_ord > ord('Z'):
                drive_ord = ord('A')
            self._add_mapping_row(remote=r, label=r, drive=drive_letter)
        messagebox.showinfo("Mappings created", f"Generated mappings for {len(remotes)} remotes (preview).")

    def _add_mapping_row(self, remote="new-remote", label=None, drive="X:"):
        if label is None:
            label = remote
        row = len(self.mappings) + 1
        frame = ttk.Frame(self.map_inner)
        frame.grid(row=row, column=0, sticky="ew", pady=3)
        frame.columnconfigure(0, weight=1)

        ent_remote = ttk.Entry(frame, width=32)
        ent_remote.insert(0, remote)
        ent_remote.grid(row=0, column=0, padx=2)

        ent_label = ttk.Entry(frame, width=20)
        ent_label.insert(0, label)
        ent_label.grid(row=0, column=1, padx=2)

        ent_drive = ttk.Entry(frame, width=8)
        ent_drive.insert(0, drive)
        ent_drive.grid(row=0, column=2, padx=2)

        btn_rm = ttk.Button(frame, text="Remove", width=8, command=lambda f=frame: self._remove_mapping(f))
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
        messagebox.showinfo("Removed", "Mapping removed (preview).")

    def _clear_mappings(self):
        if not self.mappings:
            return
        if not messagebox.askyesno("Clear mappings", "Clear all mappings? (preview)"):
            return
        for m in list(self.mappings):
            m['frame'].destroy()
        self.mappings.clear()
        messagebox.showinfo("Cleared", "All mappings cleared (preview).")

    def _mock_mount_all(self):
        if not self.mappings:
            messagebox.showwarning("No mappings", "No mappings defined — nothing to mount.")
            return
        lines = []
        for m in self.mappings:
            remote = m['remote_widget'].get()
            label = m['label_widget'].get()
            drive = m['drive_widget'].get()
            lines.append(f"{remote}  ->  {drive}   (label='{label}')")
        confinfo = f"Using config: {conf_basename(self.loaded_conf_path) if self.loaded_conf_path else '(none)'}"
        if self.var_password.get():
            confinfo += "  [password provided]"
        else:
            confinfo += "  [no password provided]"
        msg = "Mount All (preview)\n\n" + confinfo + "\n\nWill attempt to mount:\n\n" + "\n".join(lines)
        messagebox.showinfo("Mount All (preview)", msg)

    def _mock_unmount_all(self):
        if not self.mappings:
            messagebox.showinfo("Unmount (preview)", "No mapped drives found (preview).")
            return
        drives = [m['drive_widget'].get() for m in self.mappings]
        messagebox.showinfo("Unmount All (preview)", "Would attempt to unmount drives:\n\n" + ", ".join(drives))

    def _create_startup_for_conf(self):
        if not self.loaded_conf_path:
            messagebox.showwarning("No config", "Load a config first, then create startup.")
            return
        confname = Path(self.loaded_conf_path).stem
        startup_name = STARTUP_PREFIX + confname
        if startup_name in self.simulated_startups:
            messagebox.showinfo("Exists", f"Simulated startup already exists: {startup_name}")
            return
        self.simulated_startups.append(startup_name)
        self.lst_startups.insert(tk.END, startup_name)
        messagebox.showinfo("Created (preview)", f"Simulated startup created: {startup_name}\n(Preview-only: no files were written.)")

    def _clear_ezmount_startups(self):
        if not self.simulated_startups:
            messagebox.showinfo("Clean", "No EZMount simulated startups to clear.")
            return
        removed = list(self.simulated_startups)
        self.simulated_startups.clear()
        self.lst_startups.delete(0, tk.END)
        messagebox.showinfo("Cleaned", f"Removed {len(removed)} simulated EZMount startup entries (preview).")

    def _show_about(self):
        messagebox.showinfo("About EZMount", f"{APP_TITLE}\n\nUI-only preview.\n\nAuthor: (your name)\nContact: (optional)")
