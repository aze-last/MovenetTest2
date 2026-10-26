import pytest
import customtkinter as ctk

@pytest.fixture(scope="session")
def tk_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass
