"""Tkinter desktop UI. It deliberately never renders pairing secrets or endpoints."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse

from .device import KoboDevice, WindowsVolumeScanner, eject_volume
from .pairing import PairingClient, PairingError, parse_pairing_code
from .service import KoboPatcher, PatchError


class KoboPatcherApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=18)
        self.master = master
        self.scanner = WindowsVolumeScanner()
        self.devices: list[KoboDevice] = []
        self._device_selected = False
        self.device_var = tk.StringVar()
        self.code_var = tk.StringVar()
        self.backup_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Connect your Kobo in USB storage mode, then scan.")
        self._build()
        self.pack(fill="both", expand=True)
        self.scan()

    def _build(self) -> None:
        self.master.title("BookFlow Kobo Patcher")
        self.master.minsize(610, 430)
        ttk.Label(self, text="BookFlow Kobo Patcher", font=("Segoe UI", 15, "bold")).grid(
            column=0, row=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            self,
            text="Only api_endpoint in Kobo eReader.conf is changed. KoboReader.sqlite is never opened.",
            wraplength=570,
        ).grid(column=0, row=1, columnspan=3, sticky="w", pady=(4, 16))
        ttk.Label(self, text="Detected Kobo").grid(column=0, row=2, sticky="w")
        self.device_box = ttk.Combobox(
            self, textvariable=self.device_var, state="readonly", width=56
        )
        self.device_box.grid(column=0, row=3, columnspan=2, sticky="ew", pady=(2, 4))
        self.device_box.bind("<<ComboboxSelected>>", self._on_device_selected)
        ttk.Button(self, text="Scan again", command=self.scan).grid(
            column=2, row=3, sticky="e", padx=(8, 0)
        )

        ttk.Separator(self).grid(column=0, row=4, columnspan=3, sticky="ew", pady=14)
        ttk.Label(self, text="BookFlow pairing code").grid(column=0, row=5, sticky="w")
        ttk.Entry(self, textvariable=self.code_var, show="•", width=60).grid(
            column=0, row=6, columnspan=3, sticky="ew", pady=(2, 5)
        )
        ttk.Button(self, text="Patch Kobo", command=self.patch).grid(column=0, row=7, sticky="w")
        ttk.Label(
            self,
            text="Patching may affect Kobo Store or OverDrive. Confirm the device and server before continuing.",
            wraplength=570,
        ).grid(column=0, row=8, columnspan=3, sticky="w", pady=(6, 12))

        ttk.Separator(self).grid(column=0, row=9, columnspan=3, sticky="ew", pady=8)
        ttk.Label(self, text="Restore from BookFlow backup").grid(column=0, row=10, sticky="w")
        self.backup_box = ttk.Combobox(
            self, textvariable=self.backup_var, state="readonly", width=56
        )
        self.backup_box.grid(column=0, row=11, columnspan=2, sticky="ew", pady=(2, 4))
        ttk.Button(self, text="Restore backup", command=self.restore_backup).grid(
            column=2, row=11, sticky="e", padx=(8, 0)
        )
        ttk.Button(self, text="Restore official Kobo sync", command=self.restore_official).grid(
            column=0, row=12, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            self,
            text="This changes only api_endpoint back to Kobo; it does not factory-reset your reader.",
            wraplength=570,
        ).grid(column=0, row=13, columnspan=3, sticky="w", pady=(4, 14))

        ttk.Separator(self).grid(column=0, row=14, columnspan=3, sticky="ew", pady=8)
        ttk.Label(self, textvariable=self.status_var, wraplength=470).grid(
            column=0, row=15, columnspan=2, sticky="w"
        )
        ttk.Button(self, text="Safely eject", command=self.eject).grid(
            column=2, row=15, sticky="e", padx=(8, 0)
        )
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

    def _selected_device(self) -> KoboDevice | None:
        index = self.device_box.current()
        return (
            self.devices[index]
            if self._device_selected and 0 <= index < len(self.devices)
            else None
        )

    def _on_device_selected(self, _event: object) -> None:
        self._device_selected = self.device_box.current() >= 0
        self._load_backups()

    def scan(self) -> None:
        self.devices = self.scanner.scan()
        values = [self._device_label(device) for device in self.devices]
        self.device_box["values"] = values
        self._device_selected = len(values) == 1
        if len(values) == 1:
            self.device_box.current(0)
            self.status_var.set("Found one Kobo reader.")
        elif values:
            self.device_box.set("")
            self.status_var.set(f"Found {len(values)} Kobo readers. Select the intended one.")
        else:
            self.device_var.set("")
            self.status_var.set(
                "No Kobo found. Ensure USB storage mode is active, then scan again."
            )
        self._load_backups()

    @staticmethod
    def _device_label(device: KoboDevice) -> str:
        details = ", ".join(
            value for value in (device.platform, device.firmware, device.serial_masked) if value
        )
        return f"{device.display_name}{' (' + details + ')' if details else ''}"

    def _load_backups(self) -> None:
        device = self._selected_device()
        backups = KoboPatcher(device).available_backups() if device else []
        values = [str(item) for item in backups]
        self.backup_box["values"] = values
        self.backup_var.set(values[0] if values else "")

    def _patcher(self) -> KoboPatcher | None:
        device = self._selected_device()
        if not device:
            messagebox.showerror(
                "No Kobo selected", "Connect and select exactly one Kobo before continuing."
            )
            return None
        return KoboPatcher(device)

    def patch(self) -> None:
        patcher = self._patcher()
        if not patcher:
            return
        try:
            code = parse_pairing_code(self.code_var.get())
        except PairingError as exc:
            messagebox.showerror("Invalid pairing code", str(exc))
            return
        warning = "\n\nThis is a private HTTP address." if code.insecure_lan else ""
        try:
            current = patcher.current_endpoint()
        except PatchError as exc:
            messagebox.showerror("Could not inspect Kobo", str(exc))
            return
        current_host = urlparse(current).netloc if current else "not configured"
        if not messagebox.askyesno(
            "Confirm Kobo patch",
            f"Patch {patcher.device.display_name}?\n\nConfiguration file:\n{patcher.path}\n\n"
            f"Current API host: {current_host}\nNew BookFlow host: {code.host}{warning}\n\n"
            "Only api_endpoint will change.",
        ):
            return
        session: str | None = None
        client = PairingClient(code)
        try:
            session = client.claim()
            endpoint = client.complete(session, patcher.device.label or "Kobo")
            result = patcher.patch(endpoint)
        except (PairingError, PatchError) as exc:
            revoked = client.revoke(session) if session else True
            if revoked:
                self.status_var.set("Kobo patch failed. The temporary pairing token was revoked.")
                messagebox.showerror("Could not patch Kobo", str(exc))
            else:
                warning = (
                    "\n\nWarning: BookFlow could not confirm that the newly issued "
                    "pairing token was revoked. Open BookFlow's Kobo settings and rotate "
                    "the device token before trying again."
                )
                self.status_var.set(
                    "Kobo patch failed. BookFlow could not confirm token revocation."
                )
                messagebox.showerror("Could not patch Kobo", f"{exc}{warning}")
            return
        self.code_var.set("")
        self.status_var.set(f"Kobo patched successfully. Safety backup: {result.backup_path.name}")
        self._load_backups()
        messagebox.showinfo(
            "Kobo patched", "BookFlow sync was configured. You may now safely eject the Kobo."
        )

    def restore_backup(self) -> None:
        patcher = self._patcher()
        if not patcher:
            return
        value = self.backup_var.get()
        if not value:
            messagebox.showerror("No backup", "No BookFlow backup is available for this Kobo.")
            return
        if not messagebox.askyesno(
            "Confirm restore", "Restore the selected BookFlow configuration backup?"
        ):
            return
        try:
            result = patcher.restore_backup(Path(value))
        except PatchError as exc:
            messagebox.showerror("Could not restore backup", str(exc))
            return
        self.status_var.set(
            f"Configuration restored. Pre-restore safety backup: {result.backup_path.name}"
        )
        self._load_backups()

    def restore_official(self) -> None:
        patcher = self._patcher()
        if not patcher:
            return
        if not messagebox.askyesno(
            "Restore official Kobo sync",
            "Set only api_endpoint back to the official Kobo server? This is not a factory reset.",
        ):
            return
        try:
            result = patcher.restore_official_sync()
        except PatchError as exc:
            messagebox.showerror("Could not restore Kobo sync", str(exc))
            return
        self.status_var.set(
            f"Official Kobo sync restored. Safety backup: {result.backup_path.name}"
        )
        self._load_backups()

    def eject(self) -> None:
        device = self._selected_device()
        if not device:
            return
        if eject_volume(device.root):
            self.status_var.set("Kobo was safely ejected. You can unplug it.")
        else:
            messagebox.showwarning(
                "Could not eject",
                "Windows could not safely eject the Kobo. Close open files and use Windows' Safely Remove Hardware icon before unplugging.",
            )


def main() -> None:
    root = tk.Tk()
    KoboPatcherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
