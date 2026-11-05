from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def print_setup_instructions() -> None:
    print("=== Meredian Band Agent Setup ===")
    print("1. Open https://app.band.ai/agents and create an agent named 'Meredian'.")
    print("2. Copy the generated Agent ID (UUID) and Band API Key.")
    print("3. Put them in `.env` (BAND_AGENT_ID, BAND_API_KEY, BAND_ROOM_ID, BAND_MODE=live)")
    print("   or in `agent_config.yaml`.")


if __name__ == "__main__":
    print_setup_instructions()

