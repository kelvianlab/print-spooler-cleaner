"""One-button GUI to clear a jammed Windows Print Spooler.

Stops the Spooler service, deletes stuck job files under
C:\\Windows\\System32\\spool\\PRINTERS, then restarts the service.
Requires Administrator privileges (Windows only); it asks for them once
at startup so the cleanup itself is a single click.
"""

import ctypes
import datetime
import re
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext

SPOOL_DIR = Path(r"C:\Windows\System32\spool\PRINTERS")
LOG_FILE = Path(__file__).with_name("spooler_cleaner.log")

CREATE_NO_WINDOW = 0x08000000
SERVICE_STOPPED = 1
SERVICE_RUNNING = 4


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except OSError:
        return False


def relaunch_as_admin() -> bool:
    script_path = Path(__file__).resolve()
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script_path}"', str(script_path.parent), 1
    )
    return result > 32


def run_command(args: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a console command without flashing a window or waiting on stdin."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return -1, f"Command timed out after {timeout}s: {' '.join(args)}"
    except OSError as exc:
        return -1, str(exc)
    return result.returncode, (result.stdout or result.stderr).strip()


def spooler_state() -> int | None:
    """Return the Spooler's numeric service state, or None if unknown.

    The numeric code is used instead of the status text because that text
    is translated on non-English Windows installs.
    """
    code, output = run_command(["sc", "query", "spooler"], timeout=15)
    if code != 0:
        return None
    match = re.search(r"STATE\s+:\s+(\d+)", output)
    return int(match.group(1)) if match else None


def wait_for_state(target: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if spooler_state() == target:
            return True
        time.sleep(0.5)
    return False


class SpoolerCleanerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Print Spooler Cleaner")
        root.geometry("480x360")
        root.minsize(400, 300)

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
        line = f"[{datetime.datetime.now():%H:%M:%S}] {message}"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.root.update_idletasks()
        try:
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def on_click(self) -> None:
        confirmed = messagebox.askyesno(
            "Confirm",
            "This will stop the Print Spooler, permanently delete any "
            "stuck print jobs, and restart the service.\n\nContinue?",
        )
        if not confirmed:
            self.log("Cancelled by user.")
            return

        self.button.configure(state="disabled")
        try:
            self.clean_spooler()
        finally:
            self.button.configure(state="normal")

    def clean_spooler(self) -> None:
        if not self.stop_spooler():
            return

        deleted, failed = self.clear_spool_files()
        self.log(f"Deleted {deleted} stuck job file(s).")
        if failed:
            self.log(f"Could not delete {failed} file(s) (still locked).")

        self.start_spooler(deleted, failed)

    def stop_spooler(self) -> bool:
        if spooler_state() == SERVICE_STOPPED:
            self.log("Spooler service was already stopped.")
            return True

        self.log("Stopping Spooler service...")
        # /y auto-confirms stopping dependent services, which otherwise
        # blocks on an interactive prompt this GUI can never answer.
        code, output = run_command(["net", "stop", "spooler", "/y"], timeout=60)
        if wait_for_state(SERVICE_STOPPED):
            self.log("Spooler service stopped.")
            return True

        detail = output or f"exit code {code}"
        self.log(f"Failed to stop Spooler service: {detail}")
        messagebox.showerror("Error", f"Could not stop the Spooler service:\n{detail}")
        return False

    def start_spooler(self, deleted: int, failed: int) -> None:
        self.log("Starting Spooler service...")
        code, output = run_command(["net", "start", "spooler"], timeout=60)
        if wait_for_state(SERVICE_RUNNING):
            self.log("Spooler service is running.")
            summary = f"Print Spooler restarted.\n\n{deleted} stuck job(s) cleared."
            if failed:
                summary += f"\n{failed} file(s) were locked and could not be deleted."
            messagebox.showinfo("Done", summary)
            return

        detail = output or f"exit code {code}"
        self.log(f"Failed to start Spooler service: {detail}")
        messagebox.showerror(
            "Error",
            f"Spool files were cleared, but the Spooler service failed to "
            f"restart:\n{detail}\n\nPlease start it manually from services.msc.",
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
        remaining = []
        for path in files:
            if self.try_delete(path):
                deleted += 1
            else:
                remaining.append(path)

        # Windows can hold spool handles open for a moment after the service
        # stops, so locked files get a second chance before being reported.
        if remaining:
            time.sleep(1.0)
            still_locked = []
            for path in remaining:
                if self.try_delete(path):
                    deleted += 1
                else:
                    still_locked.append(path)
            for path in still_locked:
                self.log(f"  Skipped {path.name}: still locked")
            return deleted, len(still_locked)

        return deleted, 0

    @staticmethod
    def try_delete(path: Path) -> bool:
        try:
            path.unlink()
            return True
        except OSError:
            return False


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass


def main() -> None:
    if sys.platform != "win32":
        print("This tool only works on Windows.")
        sys.exit(1)

    enable_dpi_awareness()

    if not is_admin():
        prompt = tk.Tk()
        prompt.withdraw()
        answer = messagebox.askyesno(
            "Administrator required",
            "Print Spooler Cleaner needs Administrator privileges to stop "
            "the Spooler service and delete stuck print jobs.\n\n"
            "Restart as Administrator now?",
        )
        if not answer:
            prompt.destroy()
            sys.exit(0)
        if not relaunch_as_admin():
            messagebox.showerror(
                "Error",
                "Could not restart as Administrator. You may have cancelled "
                "the permission prompt.\n\nTry right-clicking "
                "spooler_cleaner.py and choosing 'Run as administrator'.",
            )
        prompt.destroy()
        sys.exit(0)

    root = tk.Tk()
    SpoolerCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
