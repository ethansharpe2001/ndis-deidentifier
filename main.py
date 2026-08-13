"""PyInstaller entry point - launches the de-identifier GUI.

Importing `app.gui` transitively pulls in numpy, spaCy and presidio (all
native-extension-backed). On Windows, a DLL belonging to one of those (most
often numpy's OpenBLAS, whose filename alone is ~90 characters) can fail to
load if the app is installed somewhere with a long path - Windows silently
refuses to load a DLL whose full path exceeds the ~260-character MAX_PATH
limit, and that surfaces as an opaque "DLL load failed" ImportError with no
obvious connection to "where you put the folder". This wrapper catches that
class of startup failure and shows a plain-language, actionable dialog
instead of a bare traceback.
"""
import sys
import traceback


def _show_startup_error(exc: BaseException) -> None:
    import tkinter as tk
    from tkinter import messagebox

    install_path = sys.executable if getattr(sys, "frozen", False) else __file__
    path_len = len(install_path)
    is_dll_error = isinstance(exc, ImportError) and "DLL load failed" in str(exc)

    lines = ["NDIS Behaviour Support Plan De-identifier failed to start.", ""]
    if is_dll_error and path_len > 150:
        lines += [
            "This usually means the app is installed at a path that's too long "
            "for Windows to handle - some of its bundled files (particularly "
            "numpy) come close to that limit on their own.",
            "",
            f"Current install path is {path_len} characters:",
            install_path,
            "",
            "Fix: move the whole app folder somewhere with a shorter path, e.g. "
            "C:\\NDIS-Deidentifier\\, and run it from there instead.",
        ]
    elif is_dll_error:
        lines += [
            "A required system component (a DLL) failed to load. This can "
            "happen if antivirus software quarantined part of the app, or if "
            "the download/extraction was incomplete.",
            "",
            "Fix: re-download and fully re-extract the app (right-click the "
            "zip and choose \"Extract All\", rather than opening it and "
            "dragging files out) to a short path like C:\\NDIS-Deidentifier\\.",
        ]
    else:
        lines += [
            "Unexpected error during startup:",
            "",
            f"{type(exc).__name__}: {exc}",
        ]

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("NDIS De-identifier - Startup Error", "\n".join(lines))
    root.destroy()


if __name__ == "__main__":
    try:
        from app.gui import main
    except Exception as exc:  # noqa: BLE001 - last line of defense before a bare crash
        traceback.print_exc()
        try:
            _show_startup_error(exc)
        except Exception:
            pass  # tkinter itself is unavailable/broken - nothing more we can do
        sys.exit(1)

    main()
