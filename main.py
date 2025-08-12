"""
EZMount — Improved UI + Startup integration

Features added/overhauled:
- Clean, roomy UI using ttk.Panedwindow + grid to avoid squeezed buttons.
- Auto-detection of rclone on PATH; shows path in status bar.
- Load rclone.conf (read-only view) and parse remotes.
- Bucket-aware auto-mapping (prompts for additional buckets on S3 remotes).
- Editable mapping rows with: Remote[:path], Label, Drive/Mount target, Add-to-startup checkbox.
- Mount All / Unmount All (starts/stops rclone mount background processes and displays console output).
- When unmounting, user is asked if they want to restart Explorer (Windows). If yes, it restarts explorer.exe.
- Create startup entries for selected mappings: Windows -> shell:startup (.cmd files with STARTUP_PREFIX). Linux -> ~/.config/autostart (.desktop files).
- Clear startup entries that match STARTUP_PREFIX.
- Logs, active mounts list, and better layout/padding for comfortable UX.

Notes & caveats:
- This app will create real files in the user's startup/autostart directory when adding mappings to startup. You will be asked for confirmation.
- You need rclone installed and available on PATH for mounting to work.
- Unmounting is implemented by terminating rclone processes. Depending on your platform/permissions you may need elevated privileges.
- On Windows, restarting explorer is implemented via `taskkill /f /im explorer.exe` and then `start explorer.exe`.

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
import platform
import shlex

# constants
APP_TITLE = "EZMount"
STARTUP_PREFIX = "EZMount_"
LOG_MAX_CHARS = 20000

# ---------- utilities ----------

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


def conf_basename(path):
    try:
        return Path(path).name
    except Exception:
        return "(none)"


def get_windows_startup_folder():
    # Typical shell:startup folder
    appdata = os.getenv('APPDATA')
    if not appdata:
        return None
    return Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


def get_linux_autostart_folder():
    home = Path.home()
    return home / '.config' / 'autostart'


def get_startup_folder():
    if os.name == 'nt':
        p = get_windows_startup_folder()
        return p
    else:
        return get_linux_autostart_folder()


def ensure_startup_folder():
    p = get_startup_folder()
    if p is None:
        return None
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- main app ----------
class EZMountApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} — rclone UI")
        self.geometry("1200x760")

        self.loaded_conf_path = None
        self.loaded_conf_text = ""
        self.conf_sections = {}

        self.mappings = []  # list of mapping dicts containing widgets
        self.active_mounts = []  # list of dicts {mapping_txt, proc, started_at}

        self.rclone_path = shutil.which('rclone')

        self._build_styles()
        self._build_ui()

        # start small thread to poll process status and UI updates
        self.after(1000, self._refresh_status_periodic)

    def _build_styles(self):
        style = ttk.Style(self)
        # platform native theme may be used; increase padding for controls
        style.configure('TButton', padding=6)
        style.configure('TLabel', padding=2)
        style.configure('TEntry', padding=2)

    def _build_ui(self):
        pad = 10
        toolbar = ttk.Frame(self, padding=(pad, pad//2))
        toolbar.pack(fill=tk.X)

        btn_select = ttk.Button(toolbar, text='Select rclone.conf', command=self.select_conf)
        btn_select.pack(side=tk.LEFT, padx=(0,8))

        self.lbl_confpath = ttk.Label(toolbar, text='(no config loaded)')
        self.lbl_confpath.pack(side=tk.LEFT, padx=(0,12))

        self.lbl_rclone = ttk.Label(toolbar, text=f'rclone: {self.rclone_path or "(not found)"}')
        self.lbl_rclone.pack(side=tk.LEFT)

        ttk.Label(toolbar, text=' ' * 6).pack(side=tk.LEFT)
        ttk.Label(toolbar, text='Config password:').pack(side=tk.LEFT, padx=(8,6))
        self.var_password = tk.StringVar()
        ent_pw = ttk.Entry(toolbar, textvariable=self.var_password, show='*', width=30)
        ent_pw.pack(side=tk.LEFT)

        # main area: paned window for conf view and mappings
        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0,pad))

        # left: conf viewer
        left = ttk.Frame(main, padding=pad)
        main.add(left, weight=1)
        ttk.Label(left, text='rclone.conf (read-only)', font=(None, 11, 'bold')).pack(anchor='w')
        self.txt_conf = scrolledtext.ScrolledText(left, wrap=tk.NONE, height=30)
        self.txt_conf.pack(fill=tk.BOTH, expand=True, pady=(6,0))
        self.txt_conf.configure(state=tk.DISABLED)

        # right: mappings area
        right = ttk.Frame(main, padding=pad)
        main.add(right, weight=1)

        hdr = ttk.Label(right, text='Mappings', font=(None, 12, 'bold'))
        hdr.pack(anchor='w')

        controls = ttk.Frame(right)
        controls.pack(fill=tk.X, pady=(6,8))
        ttk.Button(controls, text='Auto-generate mappings', command=self.auto_generate_mappings).pack(side=tk.LEFT)
        ttk.Button(controls, text='Add mapping', command=self.add_mapping_row).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(controls, text='Clear mappings', command=self.clear_mappings).pack(side=tk.LEFT, padx=(6,0))

        ttk.Button(controls, text='Mount All', command=self.mount_all).pack(side=tk.RIGHT)
        ttk.Button(controls, text='Unmount All', command=self.unmount_all).pack(side=tk.RIGHT, padx=(6,0))

        # mapping list header
        header_row = ttk.Frame(right)
        header_row.pack(fill=tk.X)
        header_row.columnconfigure(0, weight=4)
        header_row.columnconfigure(1, weight=2)
        header_row.columnconfigure(2, weight=1)
        header_row.columnconfigure(3, weight=1)

        ttk.Label(header_row, text='Remote[:path]').grid(row=0, column=0, sticky='w')
        ttk.Label(header_row, text='Label').grid(row=0, column=1, sticky='w')
        ttk.Label(header_row, text='Drive / Mount').grid(row=0, column=2, sticky='w')
        ttk.Label(header_row, text='Add to startup').grid(row=0, column=3, sticky='w')

        # scrollable mapping area
        map_frame = ttk.Frame(right)
        map_frame.pack(fill=tk.BOTH, expand=True, pady=(6,0))

        self.map_canvas = tk.Canvas(map_frame, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(map_frame, orient='vertical', command=self.map_canvas.yview)
        self.map_inner = ttk.Frame(self.map_canvas)
        self.map_inner.bind('<Configure>', lambda e: self.map_canvas.configure(scrollregion=self.map_canvas.bbox('all')))
        self.map_canvas.create_window((0,0), window=self.map_inner, anchor='nw')
        self.map_canvas.configure(yscrollcommand=vsb.set)
        self.map_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # bottom area: active mounts + logs + startup management
        bottom = ttk.Frame(self, padding=pad)
        bottom.pack(fill=tk.BOTH)

        leftbot = ttk.Frame(bottom)
        leftbot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(leftbot, text='Active mounts', font=(None, 11, 'bold')).pack(anchor='w')
        self.lst_active = tk.Listbox(leftbot, height=8)
        self.lst_active.pack(fill=tk.BOTH, expand=True, pady=(6,0))

        midbot = ttk.Frame(bottom)
        midbot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,8))
        ttk.Label(midbot, text='Console output', font=(None, 11, 'bold')).pack(anchor='w')
        self.txt_log = scrolledtext.ScrolledText(midbot, height=8)
        self.txt_log.pack(fill=tk.BOTH, expand=True, pady=(6,0))
        self.txt_log.configure(state=tk.DISABLED)

        rightbot = ttk.Frame(bottom)
        rightbot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(rightbot, text='Startup (system)', font=(None, 11, 'bold')).pack(anchor='w')
        sp = ttk.Frame(rightbot)
        sp.pack(fill=tk.X, pady=(6,0))
        ttk.Button(sp, text='Add selected mappings to startup', command=self.add_selected_to_startup).pack(side=tk.LEFT)
        ttk.Button(sp, text='Clear EZMount startups', command=self.clear_startups).pack(side=tk.LEFT, padx=(6,0))

        self.lbl_startup_folder = ttk.Label(rightbot, text='Startup folder: ' + str(get_startup_folder()))
        self.lbl_startup_folder.pack(anchor='w', pady=(6,0))

    # ---------- config load ----------
    def select_conf(self):
        p = filedialog.askopenfilename(title='Select rclone.conf', filetypes=[('conf','*.conf'), ('All','*.*')])
        if not p:
            return
        try:
            text = Path(p).read_text(encoding='utf-8')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to read file:\n{e}')
            return
        self.loaded_conf_path = p
        self.loaded_conf_text = text
        self.conf_sections = parse_conf_sections(text)

        self.txt_conf.configure(state=tk.NORMAL)
        self.txt_conf.delete('1.0', tk.END)
        self.txt_conf.insert(tk.END, text)
        self.txt_conf.configure(state=tk.DISABLED)

        self.lbl_confpath.config(text=conf_basename(p))

        # auto-generate mappings
        self.auto_generate_mappings()

    # ---------- mapping rows ----------
    def add_mapping_row(self, remote='new-remote:', label=None, drive='X:', startup=False):
        if label is None:
            label = remote
        row = len(self.mappings)
        frame = ttk.Frame(self.map_inner, padding=4)
        frame.grid(row=row, column=0, sticky='ew', pady=2)
        frame.columnconfigure(0, weight=4)
        frame.columnconfigure(1, weight=2)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)

        ent_remote = ttk.Entry(frame)
        ent_remote.insert(0, remote)
        ent_remote.grid(row=0, column=0, sticky='ew', padx=4)

        ent_label = ttk.Entry(frame)
        ent_label.insert(0, label)
        ent_label.grid(row=0, column=1, sticky='ew', padx=4)

        ent_drive = ttk.Entry(frame, width=12)
        ent_drive.insert(0, drive)
        ent_drive.grid(row=0, column=2, sticky='ew', padx=4)

        var_startup = tk.BooleanVar(value=startup)
        chk = ttk.Checkbutton(frame, variable=var_startup)
        chk.grid(row=0, column=3, sticky='w', padx=8)

        btn_rm = ttk.Button(frame, text='Remove', command=lambda f=frame: self._remove_mapping(f))
        btn_rm.grid(row=0, column=4, padx=(8,0))

        self.mappings.append({
            'frame': frame,
            'remote_widget': ent_remote,
            'label_widget': ent_label,
            'drive_widget': ent_drive,
            'startup_var': var_startup
        })

    def _remove_mapping(self, frame):
        for i, m in enumerate(list(self.mappings)):
            if m['frame'] == frame:
                m['frame'].destroy()
                self.mappings.pop(i)
                break
        # re-grid remaining rows for clean look
        for idx, mm in enumerate(self.mappings):
            mm['frame'].grid_configure(row=idx)

    def clear_mappings(self):
        if not self.mappings:
            return
        if not messagebox.askyesno('Clear mappings', 'Clear all mappings?'):
            return
        for m in list(self.mappings):
            m['frame'].destroy()
        self.mappings.clear()

    # ---------- auto-generate mapping logic (bucket-aware) ----------
    def auto_generate_mappings(self):
        # clear existing mappings
        for m in list(self.mappings):
            m['frame'].destroy()
        self.mappings.clear()

        if not self.conf_sections:
            messagebox.showinfo('No config', 'Load an rclone.conf first.')
            return

        drive_ord = ord('X')
        for section, kv in self.conf_sections.items():
            type_val = kv.get('type', '').lower()
            bucket_val = kv.get('bucket') or kv.get('bucket_name')

            if type_val == 's3' or bucket_val:
                # default mapping for bucket key
                if bucket_val:
                    remote_spec = f"{section}:{bucket_val}"
                    self.add_mapping_row(remote=remote_spec, label=f"{section}-{bucket_val}", drive=f"{chr(drive_ord)}:")
                    drive_ord = self._next_drive_ord(drive_ord)

                add_more = messagebox.askyesno('Additional buckets?', f"Remote '{section}' looks like S3 or has a bucket.\nDo you want to add additional buckets for this remote?")
                if add_more:
                    bucket_input = simpledialog.askstring('Enter buckets', f"Enter bucket names for '{section}' (comma-separated):")
                    if bucket_input:
                        buckets = [b.strip() for b in bucket_input.split(',') if b.strip()]
                        for b in buckets:
                            remote_spec = f"{section}:{b}"
                            self.add_mapping_row(remote=remote_spec, label=f"{section}-{b}", drive=f"{chr(drive_ord)}:")
                            drive_ord = self._next_drive_ord(drive_ord)
                continue

            # default single mapping
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
            messagebox.showerror('Missing rclone', 'rclone executable not found on PATH. Install rclone first.')
            return
        if not self.mappings:
            messagebox.showinfo('No mappings', 'No mappings defined — nothing to mount.')
            return

        to_mount = []
        for m in self.mappings:
            remote = m['remote_widget'].get().strip()
            label = m['label_widget'].get().strip()
            drive = m['drive_widget'].get().strip()
            if not remote:
                continue
            if self._is_drive_in_use(drive):
                resp = messagebox.askyesno('Drive in use', f'Drive {drive} appears to be in use.\nSkip this mapping?')
                if resp:
                    continue
            to_mount.append((remote, label, drive))

        if not to_mount:
            return

        for remote, label, drive in to_mount:
            t = threading.Thread(target=self._start_mount_process, args=(remote, label, drive), daemon=True)
            t.start()

    def _is_drive_in_use(self, drive_str: str) -> bool:
        if os.name == 'nt':
            d = drive_str.strip()
            # normalize 'X:' or 'X:\'
            if len(d) >= 2 and d[1] == ':':
                dpath = d[0:2] + '\\'
                return Path(dpath).exists()
            return Path(d).exists()
        else:
            return Path(drive_str).exists()

    def _start_mount_process(self, remote: str, label: str, drive: str):
        cmd = [self.rclone_path, 'mount', remote, drive, '--config', self.loaded_conf_path, '--vfs-cache-mode', 'writes']
        self._log(f'Starting: {shlex.join(cmd)}')

        try:
            creationflags = 0
            stdin = subprocess.PIPE
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=stdin, creationflags=creationflags)
        except Exception as e:
            self._log(f'Failed to start mount for {remote} -> {drive}: {e}')
            return

        self.active_mounts.append({'mapping': f"{remote} -> {drive}", 'process': proc, 'started_at': time.time()})
        self._refresh_active_list()

        # attempt to provide password to stdin if user filled it
        if self.var_password.get():
            try:
                proc.stdin.write((self.var_password.get() + '\n').encode('utf-8'))
                proc.stdin.flush()
            except Exception:
                pass

        try:
            for raw in proc.stdout:
                try:
                    line = raw.decode('utf-8', errors='replace')
                except Exception:
                    line = str(raw)
                self._log(line.rstrip())
        except Exception as e:
            self._log(f'Mount process ended for {remote} -> {drive}: {e}')
        finally:
            self._log(f'Mount process exited for {remote} -> {drive}')
            self.active_mounts = [am for am in self.active_mounts if am['process'] != proc]
            self._refresh_active_list()

    def _log(self, text: str):
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, text + '\n')
        content = self.txt_log.get('1.0', tk.END)
        if len(content) > LOG_MAX_CHARS:
            self.txt_log.delete('1.0', tk.END)
            self.txt_log.insert(tk.END, content[-LOG_MAX_CHARS:])
        self.txt_log.see(tk.END)
        self.txt_log.configure(state=tk.DISABLED)

    def _refresh_active_list(self):
        self.lst_active.delete(0, tk.END)
        for am in self.active_mounts:
            started = time.strftime('%H:%M:%S', time.localtime(am['started_at']))
            pid = am['process'].pid if am['process'] else 'N/A'
            self.lst_active.insert(tk.END, f"{am['mapping']}  (pid={pid})  started={started}")

    def _refresh_status_periodic(self):
        # clean up any dead processes
        changed = False
        for am in list(self.active_mounts):
            proc = am['process']
            if proc.poll() is not None:
                self.active_mounts.remove(am)
                changed = True
        if changed:
            self._refresh_active_list()
        # schedule next
        self.after(2000, self._refresh_status_periodic)

    def unmount_all(self):
        if not self.active_mounts:
            messagebox.showinfo('No mounts', 'No active mounts to unmount.')
            return
        if not messagebox.askyesno('Unmount all', f'Stop {len(self.active_mounts)} rclone mount processes?'):
            return

        for am in list(self.active_mounts):
            proc = am['process']
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
            except Exception as e:
                self._log(f'Error stopping pid {getattr(proc, "pid", None)}: {e}')
        self.active_mounts.clear()
        self._refresh_active_list()
        self._log('All mounts stopped by user.')

        # Ask about restarting explorer on Windows
        if os.name == 'nt':
            if messagebox.askyesno('Restart Explorer?', 'Do you want to restart Windows Explorer to refresh drive letters?'):
                try:
                    subprocess.run(['taskkill', '/f', '/im', 'explorer.exe'], check=False)
                    # small delay
                    time.sleep(0.5)
                    subprocess.Popen(['start', 'explorer.exe'], shell=True)
                    self._log('Explorer restart requested.')
                except Exception as e:
                    messagebox.showwarning('Explorer', f'Failed to restart explorer: {e}')

    # ---------- startup management ----------
    def add_selected_to_startup(self):
        # gather selected mappings with startup checkbox checked
        entries = []
        for m in self.mappings:
            try:
                if m['startup_var'].get():
                    remote = m['remote_widget'].get().strip()
                    label = m['label_widget'].get().strip()
                    drive = m['drive_widget'].get().strip()
                    entries.append((remote, label, drive))
            except Exception:
                continue

        if not entries:
            messagebox.showinfo('No entries', 'No mappings selected for startup (check "Add to startup").')
            return

        folder = ensure_startup_folder()
        if not folder:
            messagebox.showerror('Startup', 'Could not determine startup folder for this OS.')
            return

        if not messagebox.askyesno('Create startup', f'Create {len(entries)} startup entries in: {folder}?'):
            return

        created = 0
        for remote, label, drive in entries:
            try:
                fname = f"{STARTUP_PREFIX}{conf_basename(self.loaded_conf_path or 'config')}_{label}." + ( 'cmd' if os.name == 'nt' else 'desktop')
                fpath = folder / fname
                if os.name == 'nt':
                    # create a .cmd that starts rclone mount in background
                    cmdline = f'start "" "{self.rclone_path}" mount {shlex.quote(remote)} {shlex.quote(drive)} --config "{self.loaded_conf_path}" --vfs-cache-mode writes'
                    fpath.write_text(cmdline, encoding='utf-8')
                else:
                    # create a .desktop file
                    fcontent = (
                        '[Desktop Entry]\n'
                        'Type=Application\n'
                        f'Name={STARTUP_PREFIX}{label}\n'
                        f'Exec=sh -c "nohup {shlex.quote(self.rclone_path)} mount {shlex.quote(remote)} {shlex.quote(drive)} --config \"{self.loaded_conf_path}\" --vfs-cache-mode writes &> /dev/null &"\n'
                        'X-GNOME-Autostart-enabled=true\n'
                    )
                    fpath.write_text(fcontent, encoding='utf-8')
                created += 1
            except Exception as e:
                self._log(f'Failed to create startup for {remote}->{drive}: {e}')
        messagebox.showinfo('Created', f'Created {created} startup entries in {folder}')

    def clear_startups(self):
        folder = get_startup_folder()
        if not folder or not folder.exists():
            messagebox.showinfo('No startup folder', 'No startup/autostart folder found on this system.')
            return
        files = [p for p in folder.iterdir() if p.is_file() and p.name.startswith(STARTUP_PREFIX)]
        if not files:
            messagebox.showinfo('None found', 'No EZMount startup files found.')
            return
        if not messagebox.askyesno('Remove startups', f'Remove {len(files)} EZMount startup files from {folder}?'):
            return
        removed = 0
        for p in files:
            try:
                p.unlink()
                removed += 1
            except Exception as e:
                self._log(f'Failed to remove {p}: {e}')
        messagebox.showinfo('Removed', f'Removed {removed} startup files from {folder}')

    # ---------- periodic helpers ----------
    def _refresh_ui_startup_folder_label(self):
        sf = get_startup_folder()
        self.lbl_startup_folder.config(text='Startup folder: ' + str(sf))


if __name__ == '__main__':
    app = EZMountApp()
    app.mainloop()
