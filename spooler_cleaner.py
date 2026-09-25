"""One-button GUI to clear a jammed Windows Print Spooler.

Stops the Spooler service, deletes stuck job files under
C:\\Windows\\System32\\spool\\PRINTERS, then restarts the service.
Requires Administrator privileges (Windows only).
"""

import ctypes
import datetime
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext

SPOOL_DIR = Path(r"C:\Windows\System32\spool\PRINTERS")
LOG_FILE = Path(__file__).with_name("spooler_cleaner.log")


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except OSError:
        return False


def relaunch_as_admin() -> bool:
    script_path = str(Path(__file__).resolve())
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script_path}"', str(Path(script_path).parent), 1
    )
    return result > 32


def run_service_command(action: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["net", action, "spooler"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    ok = result.returncode == 0
    output = (result.stdout or result.stderr).strip()
    return ok, output


class SpoolerCleanerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Print Spooler Cleaner")
        root.geometry("480x360")
        root.resizable(False, False)

        self.button = tk.Button(
            root,
            text="Clear & Restart Spooler",
            font=("Segoe UI", 12, "bold"),
            height=2,
            command=self.on_click,
        )
        self.button.pack(fill="x", padx=16, pady=16)

        self.log_box = scrolledtext.ScrolledText(root, state="disabled", height=14)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def log(self, message: str) -> None:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def on_click(self) -> None:
        self.button.configure(state="disabled")
        if not is_admin():
            answer = messagebox.askyesno(
                "Administrator required",
                "This tool needs Administrator privileges to stop the "
                "Spooler service and delete stuck print jobs.\n\n"
                "Restart as Administrator now?",
            )
            if answer:
                if relaunch_as_admin():
                    self.root.destroy()
                    return
                messagebox.showerror(
                    "Error",
                    "Could not restart as Administrator. You may have "
                    "cancelled the permission prompt, or Python is not "
                    "on your PATH. Try right-clicking spooler_cleaner.py "
                    "and choosing 'Run as administrator' instead.",
                )
            self.button.configure(state="normal")
            return

        confirmed = messagebox.askyesno(
            "Confirm",
            "This will stop the Print Spooler, permanently delete any "
            "stuck print jobs, and restart the service.\n\nContinue?",
        )
        if not confirmed:
            self.log("Cancelled by user.")
            self.button.configure(state="normal")
            return

        try:
            self.clean_spooler()
        finally:
            self.button.configure(state="normal")

    def clean_spooler(self) -> None:
        self.log("Stopping Spooler service...")
        ok, output = run_service_command("stop")
        if ok:
            self.log("Spooler service stopped.")
        elif "not started" in output.lower() or "2182" in output:
            self.log("Spooler service was already stopped.")
        else:
            self.log(f"Failed to stop Spooler service: {output}")
            messagebox.showerror("Error", f"Could not stop the Spooler service:\n{output}")
            return

        deleted, failed = self.clear_spool_files()
        self.log(f"Deleted {deleted} stuck job file(s).")
        if failed:
            self.log(f"Could not delete {failed} file(s) (still in use).")

        self.log("Starting Spooler service...")
        ok, output = run_service_command("start")
        if ok or "already" in output.lower():
            self.log("Spooler service is running.")
            messagebox.showinfo("Done", "Print Spooler cleared and restarted successfully.")
        else:
            self.log(f"Failed to start Spooler service: {output}")
            messagebox.showerror(
                "Error",
                f"Spool files were cleared, but the Spooler service failed to "
                f"restart:\n{output}\n\nPlease start it manually from services.msc.",
            )

    def clear_spool_files(self) -> tuple[int, int]:
        if not SPOOL_DIR.exists():
            self.log("Spool folder not found; nothing to clear.")
            return 0, 0

        files = [p for p in SPOOL_DIR.iterdir() if p.is_file()]
        if not files:
            self.log("Spool folder is already empty.")
            return 0, 0

        deleted = 0
        failed = 0
        for path in files:
            try:
                path.unlink()
                deleted += 1
            except OSError as exc:
                failed += 1
                self.log(f"  Skipped {path.name}: {exc}")
        return deleted, failed


def main() -> None:
    if sys.platform != "win32":
        print("This tool only works on Windows.")
        sys.exit(1)

    root = tk.Tk()
    SpoolerCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
