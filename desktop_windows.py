from concurrent.futures import Future
import logging
from queue import Empty, Queue
import socket
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

import keyring
from keyring.backends.Windows import WinVaultKeyring
import uvicorn

from src.api.local_app import browser_app, user_data_directory
from src.utils.helpers import ROOT, configure_logging, load_config
from src.utils.settings import LocalSettings


def main() -> None:
    window = tk.Tk()
    window.title("Atlas")
    window.iconbitmap(str(ROOT / "src" / "api" / "web" / "atlas.ico"))
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=22)
    frame.grid()
    ttk.Label(frame, text="Atlas", font=("Segoe UI", 18, "bold")).grid(sticky="w")
    status = tk.StringVar(value="Pokretanje…")
    ttk.Label(frame, textvariable=status, wraplength=330).grid(sticky="w", pady=(8, 16))
    actions = ttk.Frame(frame)
    actions.grid(sticky="e")
    open_button = ttk.Button(actions, text="Otvori Atlas", state="disabled")
    open_button.grid(row=0, column=0, padx=(0, 8))
    quit_button = ttk.Button(actions, text="Zatvori aplikaciju")
    quit_button.grid(row=0, column=1)

    pending: Queue[Future[str]] = Queue()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/"
    data = user_data_directory()
    configure_logging(data)
    logging.info("Local browser URL %s", url)
    server = None
    closing = False
    ready = False

    def browse() -> str:
        selection: Future[str] = Future()
        pending.put(selection)
        return selection.result(timeout=300)

    def start_server() -> None:
        nonlocal server
        try:
            keyring.set_keyring(WinVaultKeyring())
            settings = LocalSettings(data)
            with browser_app(
                load_config(), database=data / "vectors.sqlite3", settings=settings, folder_picker=browse,
            ) as app:
                server = uvicorn.Server(uvicorn.Config(
                    app, host="127.0.0.1", log_config=None, access_log=False,
                    loop="asyncio", http="h11", ws="none", timeout_graceful_shutdown=5,
                ))
                if not closing:
                    server.run(sockets=[listener])
        except Exception:
            logging.exception("Atlas failed to start or stopped unexpectedly")
        finally:
            listener.close()

    worker = Thread(target=start_server, daemon=True)
    worker.start()

    def open_browser() -> None:
        if not webbrowser.open(url):
            messagebox.showinfo("Atlas", f"Otvorite ovu adresu u pregledaču:\n{url}", parent=window)

    def quit_app() -> None:
        nonlocal closing
        closing = True
        open_button.configure(state="disabled")
        quit_button.configure(state="disabled")
        status.set("Zatvaranje…")
        if server is not None:
            server.should_exit = True

    def update_window() -> None:
        nonlocal ready
        if not worker.is_alive():
            if closing:
                window.destroy()
                return
            open_button.configure(state="disabled")
            status.set(f"Atlas nije mogla da se pokrene. Dnevnik: {data / 'logs' / 'app.log'}")
        elif server is not None and server.started and not ready and not closing:
            ready = True
            status.set("Atlas radi. Ovaj prozor možete ostaviti otvoren.")
            open_button.configure(state="normal")
            if "--no-browser" not in sys.argv:
                open_browser()

        try:
            selection = pending.get_nowait()
        except Empty:
            pass
        else:
            try:
                selection.set_result("" if closing else filedialog.askdirectory(parent=window, mustexist=True))
            except tk.TclError as error:
                selection.set_exception(RuntimeError(str(error)))
        window.after(120, update_window)

    open_button.configure(command=open_browser)
    quit_button.configure(command=quit_app)
    window.protocol("WM_DELETE_WINDOW", quit_app)
    update_window()
    window.mainloop()


if __name__ == "__main__":
    main()
