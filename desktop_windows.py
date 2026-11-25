from keyring.backends.Windows import WinVaultKeyring

from src.desktop_launcher import launch


if __name__ == "__main__":
    launch(WinVaultKeyring())
