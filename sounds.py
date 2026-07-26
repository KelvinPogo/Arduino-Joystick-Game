"""Procedurally synthesized sound effects, so the game needs no external audio assets."""

import numpy as np
import pygame

SAMPLE_RATE = 44100


def _envelope(n, attack=0.01, release=0.05):
    env = np.ones(n)
    a = min(int(SAMPLE_RATE * attack), n // 2)
    r = min(int(SAMPLE_RATE * release), n // 2)
    if a > 0:
        env[:a] *= np.linspace(0, 1, a)
    if r > 0:
        env[-r:] *= np.linspace(1, 0, r)
    return env


def _tone(freq, duration, wave="sine", volume=1.0, attack=0.01, release=0.05):
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    if wave == "square":
        signal = np.sign(np.sin(2 * np.pi * freq * t))
    elif wave == "triangle":
        signal = 2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1
    else:
        signal = np.sin(2 * np.pi * freq * t)
    return signal * _envelope(n, attack, release) * volume


def _sweep(f_start, f_end, duration, wave="sine", volume=1.0, attack=0.01, release=0.05):
    n = int(SAMPLE_RATE * duration)
    freq = np.linspace(f_start, f_end, n)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    signal = np.sign(np.sin(phase)) if wave == "square" else np.sin(phase)
    return signal * _envelope(n, attack, release) * volume


def _concat(*segments):
    return np.concatenate(segments)


def _mix(*segments):
    length = max(len(s) for s in segments)
    out = np.zeros(length)
    for s in segments:
        out[: len(s)] += s
    return out


def _to_sound(signal):
    signal = np.clip(signal, -1.0, 1.0)
    stereo = np.column_stack([signal, signal])
    audio = np.ascontiguousarray((stereo * 32767).astype(np.int16))
    return pygame.sndarray.make_sound(audio)


def build_sounds():
    """Returns {name: pygame.mixer.Sound} for every effect the game triggers."""

    shoot = _sweep(1300, 900, 0.045, "sine", volume=0.35, attack=0.002, release=0.02)

    boss_shoot = _sweep(500, 320, 0.09, "square", volume=0.28, attack=0.003, release=0.04)

    health_up = _concat(
        _tone(523.25, 0.09, "sine", 0.5, 0.005, 0.03),   # C5
        _tone(659.25, 0.09, "sine", 0.5, 0.005, 0.03),   # E5
        _tone(783.99, 0.16, "sine", 0.55, 0.005, 0.08),  # G5
    )

    shield = _mix(
        _sweep(220, 660, 0.22, "triangle", volume=0.4, attack=0.01, release=0.08),
        _tone(1320, 0.22, "sine", 0.15, 0.02, 0.1),
    )

    game_over = _concat(
        _tone(392.00, 0.22, "sine", 0.5, 0.01, 0.05),   # G4
        _tone(311.13, 0.22, "sine", 0.5, 0.01, 0.05),   # Eb4
        _tone(196.00, 0.45, "sine", 0.55, 0.01, 0.3),   # G3
    )

    you_win = _concat(
        _tone(523.25, 0.12, "sine", 0.5, 0.005, 0.02),   # C5
        _tone(659.25, 0.12, "sine", 0.5, 0.005, 0.02),   # E5
        _tone(783.99, 0.12, "sine", 0.5, 0.005, 0.02),   # G5
        _tone(1046.50, 0.35, "sine", 0.6, 0.005, 0.2),   # C6
    )

    return {
        "shoot": _to_sound(shoot),
        "boss_shoot": _to_sound(boss_shoot),
        "health_up": _to_sound(health_up),
        "shield": _to_sound(shield),
        "game_over": _to_sound(game_over),
        "you_win": _to_sound(you_win),
    }
