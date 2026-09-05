def main():
    from .ui import CarriolaApp

    try:
        CarriolaApp().mainloop()
    except Exception as exc:
        import logging
        from tkinter import messagebox

        logging.getLogger("Carriola").exception("Falha ao abrir o aplicativo")
        messagebox.showerror("Carriola", f"Não foi possível abrir o aplicativo.\n\n{exc}")
        raise


if __name__ == "__main__":
    main()
