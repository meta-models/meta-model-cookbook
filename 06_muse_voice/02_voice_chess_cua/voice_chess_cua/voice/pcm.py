# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Standard-library PCM conversion, resampling, and framing."""

from __future__ import annotations

from collections.abc import Iterable
from math import floor, isfinite, sqrt
from struct import iter_unpack, pack

SAMPLE_RATE = 24_000
CHANNEL_COUNT = 1
CHUNK_DURATION_MILLISECONDS = 80
FRAMES_PER_CHUNK = SAMPLE_RATE * CHUNK_DURATION_MILLISECONDS // 1_000
BYTES_PER_FRAME = 2
BYTES_PER_CHUNK = FRAMES_PER_CHUNK * BYTES_PER_FRAME


def float_samples_to_pcm16le(samples: Iterable[float]) -> bytes:
    output = bytearray()
    for sample in samples:
        finite_sample = float(sample) if isfinite(sample) else 0.0
        clamped = min(1.0, max(-1.0, finite_sample))
        scaled = int(clamped * (32_767 if clamped >= 0 else 32_768))
        output.extend(pack("<h", scaled))
    return bytes(output)


def normalized_pcm16le_rms(data: bytes) -> float:
    """Return normalized RMS for a nonempty buffer of complete PCM16LE samples."""

    if not isinstance(data, bytes):
        raise TypeError("PCM data must be bytes")
    if not data or len(data) % BYTES_PER_FRAME:
        raise ValueError("PCM data must contain complete two-byte samples")

    sample_count = len(data) // BYTES_PER_FRAME
    sum_of_squares = sum(sample * sample for (sample,) in iter_unpack("<h", data))
    normalized = sqrt(sum_of_squares / sample_count) / 32_768
    return min(1.0, max(0.0, normalized))


pcm16le_normalized_rms = normalized_pcm16le_rms


def resample_linear(
    samples: Iterable[float],
    source_rate: float,
    target_rate: float = SAMPLE_RATE,
) -> list[float]:
    """Resample one finite mono buffer with deterministic linear interpolation."""

    resampler = StreamingLinearResampler(source_rate, target_rate)
    return resampler.append(samples) + resampler.finish()


class StreamingLinearResampler:
    """Linear resampler that preserves interpolation phase across input buffers."""

    def __init__(self, source_rate: float, target_rate: float = SAMPLE_RATE) -> None:
        if not isfinite(source_rate) or source_rate <= 0:
            raise ValueError("source rate must be finite and positive")
        if not isfinite(target_rate) or target_rate <= 0:
            raise ValueError("target rate must be finite and positive")
        self._source_rate = float(source_rate)
        self._target_rate = float(target_rate)
        self._source_step = self._source_rate / self._target_rate
        self._samples: list[float] = []
        self._base_index = 0
        self._total_input_samples = 0
        self._output_samples = 0
        self._next_source_position = 0.0

    def append(self, samples: Iterable[float]) -> list[float]:
        incoming = [float(sample) if isfinite(sample) else 0.0 for sample in samples]
        if not incoming:
            return []
        self._samples.extend(incoming)
        self._total_input_samples += len(incoming)
        output = self._available_output()
        self._discard_consumed_prefix()
        return output

    def finish(self) -> list[float]:
        if self._total_input_samples == 0:
            return []
        expected_output_count = max(
            1,
            floor(self._total_input_samples * self._target_rate / self._source_rate),
        )
        remaining_count = expected_output_count - self._output_samples
        output: list[float] = []
        if remaining_count > 0:
            last_sample = self._samples[-1]
            output.extend([last_sample] * remaining_count)
            self._output_samples += remaining_count
            self._next_source_position += self._source_step * remaining_count
        self.clear()
        return output

    def clear(self) -> None:
        self._samples.clear()
        self._base_index = 0
        self._total_input_samples = 0
        self._output_samples = 0
        self._next_source_position = 0.0

    def _available_output(self) -> list[float]:
        last_index = self._base_index + len(self._samples) - 1
        output: list[float] = []
        while self._next_source_position <= last_index:
            left_index = floor(self._next_source_position)
            fraction = self._next_source_position - left_index
            right_index = left_index if fraction == 0 else left_index + 1
            if right_index > last_index:
                break
            left = self._samples[left_index - self._base_index]
            right = self._samples[right_index - self._base_index]
            output.append(left + (right - left) * fraction)
            self._output_samples += 1
            self._next_source_position += self._source_step
        return output

    def _discard_consumed_prefix(self) -> None:
        keep_from = min(
            floor(self._next_source_position),
            self._base_index + len(self._samples),
        )
        discard_count = max(0, keep_from - self._base_index)
        if discard_count:
            del self._samples[:discard_count]
            self._base_index += discard_count


class AudioPCM:
    sample_rate = SAMPLE_RATE
    channel_count = CHANNEL_COUNT
    chunk_duration_milliseconds = CHUNK_DURATION_MILLISECONDS
    frames_per_chunk = FRAMES_PER_CHUNK
    bytes_per_frame = BYTES_PER_FRAME
    bytes_per_chunk = BYTES_PER_CHUNK

    @staticmethod
    def little_endian_int16_data(samples: Iterable[float]) -> bytes:
        return float_samples_to_pcm16le(samples)

    @staticmethod
    def normalized_rms(data: bytes) -> float:
        return normalized_pcm16le_rms(data)

    @staticmethod
    def resample(
        samples: Iterable[float],
        source_rate: float,
        target_rate: float = SAMPLE_RATE,
    ) -> list[float]:
        return resample_linear(samples, source_rate, target_rate)


class PCMChunker:
    def __init__(
        self,
        chunk_size: int = BYTES_PER_CHUNK,
        maximum_pending_bytes: int = BYTES_PER_CHUNK * 100,
    ) -> None:
        if (
            isinstance(chunk_size, bool)
            or not isinstance(chunk_size, int)
            or chunk_size <= 0
        ):
            raise ValueError("chunk size must be a positive integer")
        if (
            isinstance(maximum_pending_bytes, bool)
            or not isinstance(maximum_pending_bytes, int)
            or maximum_pending_bytes < chunk_size
        ):
            raise ValueError("maximum pending bytes must be at least one chunk")
        self._chunk_size = chunk_size
        self._maximum_pending_bytes = maximum_pending_bytes
        self._pending = bytearray()

    @property
    def pending(self) -> bytes:
        return bytes(self._pending)

    def append(self, data: bytes | bytearray | memoryview) -> list[bytes]:
        self._pending.extend(data)
        chunks: list[bytes] = []
        while len(self._pending) >= self._chunk_size:
            chunks.append(bytes(self._pending[: self._chunk_size]))
            del self._pending[: self._chunk_size]
        if len(self._pending) > self._maximum_pending_bytes:
            del self._pending[: len(self._pending) - self._maximum_pending_bytes]
        return chunks

    def finish(self) -> bytes:
        tail = bytes(self._pending)
        self._pending.clear()
        return tail

    def clear(self) -> None:
        self._pending.clear()
