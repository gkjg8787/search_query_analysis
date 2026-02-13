from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LOG_OPTIONS = {"directory_path": f"{BASE_DIR}/log/"}
AI_MODEL_LIST = {
    "gemini": [
        # "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        # "gemini-2.0-flash",
        # "gemini-2.0-flash-lite",
    ]
}
