"""Compare the acoustic model with measured dEchorate reverberation at 500 Hz."""

import argparse
from io import BytesIO
from pathlib import Path
from statistics import mean
from tempfile import NamedTemporaryFile

import numpy as np
import requests
from scipy.signal import butter, sosfilt

from app.pipeline.acoustics import BANDS, rt60
from app.sources.config import DATA

DATASET = "https://sofacoustics.org/data/database/dechorate/"
RECORDINGS = ("src1_arr1_mics1-5", "src1_arr3_mics11-15", "src1_arr5_mics21-25")
LENGTH, WIDTH, HEIGHT = 6, 6, 2.4
ROOM = {
    "area_m2": LENGTH * WIDTH,
    "perimeter_m": 2 * (LENGTH + WIDTH),
    "height_m": HEIGHT,
    "volume_m3": LENGTH * WIDTH * HEIGHT,
}
# The paper documents carpet, absorbing panels and reflective laminate. These
# are fixed proxies from the app's material table, chosen before fitting any decay.
CASES = (
    ("000000", "absorbing walls and ceiling"),
    ("010000", "reflective ceiling, absorbing walls"),
    ("011100", "reflective ceiling and two walls"),
    ("011111", "reflective walls and ceiling"),
)
ABSORBING = "acoustic_panel"
REFLECTIVE = "vinyl_tile"
MID_BAND = BANDS.index("500")


def predict(code: str, *, floor=None, absorbing=None, reflective=None) -> float:
    # The six digits describe floor, ceiling, west, south, east and north.
    ceiling_reflective = code[1] == "1"
    materials = {
        "floor": "carpet_on_pad", "walls": REFLECTIVE,
        "ceiling": REFLECTIVE if ceiling_reflective else ABSORBING,
        "wall_panel_m2": WIDTH * HEIGHT * code[2:].count("0"),
        "glass_m2": 0, "furnishing": "empty",
    }
    coefficients = {
        "floor": floor, "ceiling": reflective if ceiling_reflective else absorbing,
        "walls": reflective, "wall_panels": absorbing,
    }
    overrides = {surface: {"500": value} for surface, value in coefficients.items() if value is not None}
    return rt60(ROOM, materials, absorption=overrides)[0][MID_BAND]


def t20_500(signal: np.ndarray, sample_rate: float) -> float:
    """Extrapolate an octave-band energy decay fit from -5 to -25 dB to 60 dB."""
    low, high = 500 / np.sqrt(2), 500 * np.sqrt(2)
    band = butter(4, (low, high), btype="bandpass", fs=sample_rate, output="sos")
    power = sosfilt(band, signal) ** 2
    noise_power = np.mean(power[-round(sample_rate * 0.1):])

    # Schroeder integration with a stationary noise estimate from the final 100 ms.
    remaining = np.arange(len(power), 0, -1)
    noise_energy = remaining * noise_power
    energy = np.cumsum(power[::-1])[::-1] - noise_energy
    if not np.isfinite(energy[0]) or energy[0] <= 0:
        raise ValueError("No usable 500 Hz impulse response energy")
    positive = np.maximum(energy / energy[0], np.finfo(float).tiny)
    decay_db = 10 * np.log10(positive)
    start = np.flatnonzero(decay_db <= -5)
    end = np.flatnonzero(decay_db <= -25)
    if not start.size or not end.size or end[0] - start[0] < 3 or energy[end[0]] <= noise_energy[end[0]]:
        raise ValueError("The 500 Hz decay does not have a usable 20 dB fit above the noise floor")
    fit = slice(start[0], end[0] + 1)
    time = np.arange(len(power)) / sample_rate
    slope, _ = np.polyfit(time[fit], decay_db[fit], 1)
    if slope >= 0:
        raise ValueError("The fitted 500 Hz energy is not decaying")
    return float(-60 / slope)


def read_response(h5py, path: Path) -> tuple[np.ndarray, float]:
    payload = None
    source = path
    if not path.is_file():
        response = requests.get(DATASET + path.name, timeout=30)
        response.raise_for_status()
        payload = response.content
        source = BytesIO(payload)
    with h5py.File(source, "r") as sofa:
        # The mirror repeats the same RoomDescription in both configurations.
        # The title and filename identify the recording and its condition.
        title = sofa.attrs["Title"]
        if isinstance(title, bytes):
            title = title.decode()
        if title != path.stem:
            raise ValueError(f"Unexpected SOFA title in {path.name}: {title}")
        responses = sofa["Data.IR"][:]
        rates = sofa["Data.SamplingRate"][:]
    if responses.ndim != 3 or responses.shape[:2] != (1, 5) or rates.size != 1 or rates.item() != 48000:
        raise ValueError(f"Unexpected dEchorate SOFA dimensions or sample rate in {path.name}")
    if payload is not None:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(payload)
                stream.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return responses[0], rates.item()


def compare(h5py, directory: Path, *, floor=None, absorbing=None, reflective=None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    predictions, measurements = [], []
    for code, description in CASES:
        prediction = predict(code, floor=floor, absorbing=absorbing, reflective=reflective)
        measured = []
        for recording in RECORDINGS:
            path = directory / f"dEchorate_room{code}_{recording}.sofa"
            signals, sample_rate = read_response(h5py, path)
            for microphone, signal in enumerate(signals, 1):
                try:
                    measured.append(t20_500(signal, sample_rate))
                except ValueError as exc:
                    raise ValueError(f"{path.name}, channel {microphone}: {exc}") from exc
        average = mean(measured)
        predictions.append(prediction)
        measurements.append(average)
        print(f"{code} ({description})")
        print(f"  Predicted RT60: {prediction:.3f} s")
        print(f"  Measured T20:   {average:.3f} s mean ({min(measured):.3f}–{max(measured):.3f} s, {len(measured)} channels)")
        print(f"  Absolute error: {abs(prediction - average):.3f} s")

    predicted_change = predictions[-1] - predictions[0]
    measured_change = measurements[-1] - measurements[0]
    print(f"Mean absolute error across the {len(CASES)} configurations: "
          f"{mean(abs(p - m) for p, m in zip(predictions, measurements)):.3f} s")
    print(f"Reflective minus absorbing: {predicted_change:+.3f} s predicted, {measured_change:+.3f} s measured")
    print("Fully absorbing case sensitivity (assumed panel coefficient → predicted RT60):")
    for coefficient in (0.20, 0.40, 0.60, 0.80, 0.90):
        predicted = predict("000000", floor=floor, absorbing=coefficient, reflective=reflective)
        print(f"  {coefficient:.2f} → {predicted:.3f} s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA / "benchmarks" / "dechorate",
                        help="SOFA cache directory. Missing recordings are downloaded from SOFA Acoustics.")
    parser.add_argument("--floor-500", type=float, help="Known 500 Hz floor absorption coefficient.")
    parser.add_argument("--absorbing-500", type=float, help="Known 500 Hz coefficient for the absorbing panel face.")
    parser.add_argument("--reflective-500", type=float, help="Known 500 Hz coefficient for the reflective panel face.")
    args = parser.parse_args()
    try:
        import h5py
    except ImportError:
        parser.exit(2, "Install the benchmark dependency with python -m pip install h5py.\n")
    try:
        compare(h5py, args.data_dir, floor=args.floor_500, absorbing=args.absorbing_500, reflective=args.reflective_500)
    except (OSError, KeyError, ValueError, requests.RequestException) as exc:
        parser.exit(1, f"dEchorate comparison failed: {exc}\n")


if __name__ == "__main__":
    main()
