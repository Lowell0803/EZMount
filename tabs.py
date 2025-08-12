import tkinter as tk
from tkinter import ttk, scrolledtext
import webbrowser
from logic import KOFI_URL, STARTUP_PREFIX

def build_config_tab(self, parent):
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

    left = ttk.Frame(mid)
    left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))

    lbl_conf = ttk.Label(left, text="rclone.conf (read-only):")
    lbl_conf.pack(anchor="w")

    self.txt_conf = scrolledtext.ScrolledText(left, wrap=tk.NONE, height=18)
    self.txt_conf.pack(fill=tk.BOTH, expand=True)
    self.txt_conf.configure(state=tk.DISABLED)

    right = ttk.Frame(mid, width=380)
    right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)

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

    btn_auto = ttk.Button(bottom, text="Auto-generate mappings from conf", command=self._auto_generate_mappings)
    btn_auto.pack(side=tk.LEFT)

    btn_add = ttk.Button(bottom, text="Add mapping", command=self._add_mapping_row)
    btn_add.pack(side=tk.LEFT, padx=(6,0))

    btn_clear = ttk.Button(bottom, text="Clear mappings", command=self._clear_mappings)
    btn_clear.pack(side=tk.LEFT, padx=(6,0))

    btn_mount = ttk.Button(bottom, text="Mount All", command=self._mock_mount_all)
    btn_mount.pack(side=tk.RIGHT, padx=(6,0))

    btn_unmount = ttk.Button(bottom, text="Unmount All", command=self._mock_unmount_all)
    btn_unmount.pack(side=tk.RIGHT)

def build_startup_tab(self, parent):
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
