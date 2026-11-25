from keyring.backends.macOS import Keyring

from src.desktop_launcher import launch


if __name__ == "__main__":
    launch(Keyring())
