# Print Spooler Cleaner

A one-button Windows tool that clears a jammed print queue: it stops the
Print Spooler service, deletes stuck print jobs, and restarts the service —
so you can print again without digging through Services or `services.msc`.

## What it does

1. Stops the Windows **Print Spooler** service.
2. Deletes any stuck job files in `C:\Windows\System32\spool\PRINTERS`.
3. Restarts the Print Spooler service.
4. Shows a live log of each step, and asks for confirmation before deleting
   anything.

## Requirements

- Windows 10/11
- Python 3.9+ (uses only the standard library — no extra packages needed)
- Administrator privileges (the tool detects this and offers to relaunch
  itself elevated if it isn't already running as admin)

## How to run

```
python spooler_cleaner.py
```

Click **Clear & Restart Spooler**, confirm the prompt, and watch the log.

## How it works

The Print Spooler occasionally gets stuck with a corrupted or orphaned job
that blocks the entire print queue. The usual manual fix is: open
`services.msc`, stop the Spooler service, delete files under
`spool\PRINTERS`, and start the service again. This tool automates exactly
those steps behind one button, with a confirmation step first since it
deletes files and restarts a system service.

## License

MIT — see [LICENSE](LICENSE).
