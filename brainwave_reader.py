"""
Eden — real-time dominant brainwave reader for the Unicorn Hybrid Black (BrainFlow).

Eden is an Exergis product by Taurean Lee.

Streams 8-channel EEG, computes the average power in each classic frequency
band (delta, theta, alpha, beta, gamma) and prints the dominant band live.

Usage:
    python brainwave_reader.py                 # auto-discover paired device
    python brainwave_reader.py --serial UN-XXXX # target a specific device
    python brainwave_reader.py --synthetic      # no hardware: use synthetic board
"""

import argparse
import time

import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
from brainflow.data_filter import DataFilter

# Order matches DataFilter.get_avg_band_powers output.
BANDS = [
    ("delta", "1-4 Hz"),
    ("theta", "4-8 Hz"),
    ("alpha", "8-13 Hz"),
    ("beta", "13-30 Hz"),
    ("gamma", "30-50 Hz"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read dominant EEG brainwave bands.")
    parser.add_argument(
        "--serial",
        default="",
        help="Unicorn device serial/name (e.g. UN-2021.05.36). Blank = auto-discover.",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=3.0,
        help="Analysis window length in seconds (default: 3.0).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between readings (default: 1.0).",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use BrainFlow's synthetic board for testing without hardware.",
    )
    return parser.parse_args()


def make_board(args: argparse.Namespace) -> tuple[BoardShim, int]:
    params = BrainFlowInputParams()
    if args.synthetic:
        board_id = BoardIds.SYNTHETIC_BOARD
    else:
        board_id = BoardIds.UNICORN_BOARD
        params.serial_number = args.serial
    return BoardShim(board_id, params), board_id


def render_bar(value: float, peak: float, width: int = 30) -> str:
    filled = int(round((value / peak) * width)) if peak > 0 else 0
    return "#" * filled + "-" * (width - filled)


def main() -> None:
    args = parse_args()
    BoardShim.enable_dev_board_logger()

    board, board_id = make_board(args)
    sampling_rate = BoardShim.get_sampling_rate(board_id)
    eeg_channels = BoardShim.get_eeg_channels(board_id)
    window_samples = int(args.window * sampling_rate)

    board.prepare_session()
    board.start_stream()
    print(f"Streaming from board {board_id} @ {sampling_rate} Hz. Press Ctrl+C to stop.\n")

    try:
        # Let the buffer fill before the first analysis.
        time.sleep(args.window)
        while True:
            data = board.get_current_board_data(window_samples)
            if data.shape[1] < window_samples:
                time.sleep(args.interval)
                continue

            # Average band powers across all EEG channels (returns 5 bands).
            band_powers, _ = DataFilter.get_avg_band_powers(
                data, eeg_channels, sampling_rate, True
            )

            dominant_idx = int(np.argmax(band_powers))
            peak = float(np.max(band_powers))

            print("\033[H\033[J", end="")  # clear screen
            print(f"Dominant brainwave: {BANDS[dominant_idx][0].upper()} "
                  f"({BANDS[dominant_idx][1]})\n")
            for (name, rng), power in zip(BANDS, band_powers):
                marker = " <" if name == BANDS[dominant_idx][0] else ""
                print(f"  {name:<6} {rng:<8} {power:7.3f} "
                      f"|{render_bar(power, peak)}|{marker}")
            print("\nPress Ctrl+C to stop.")

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        board.stop_stream()
        board.release_session()


if __name__ == "__main__":
    main()
