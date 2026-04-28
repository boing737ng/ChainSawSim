import numpy as np
from scipy.signal import butter, sosfilt
import warnings
import io
import wave
import struct

warnings.filterwarnings("ignore")


class ChainsawAudioModel:
    """
    Математическая модель звука бензопилы с глубоким параметрическим контролем.
    Все параметры имеют физическую интерпретацию и влияют на синтез через аналитические зависимости.
    """

    DEFAULT_PARAMS = {
        # --- Двигатель и сгорание ---
        "bore_mm": 43.0,
        "stroke_mm": 30.0,
        "compression_ratio": 9.5,
        "port_timing_deg": 135,
        "crankcase_volume_cm3": 280,
        "exhaust_length_mm": 210,
        "muffler_volume_cm3": 850,
        "reed_stiffness": 1.0,
        # --- Топливо и смесь ---
        "fuel_octane": 92,
        "oil_ratio_50_1": 1.0,
        "air_fuel_ratio": 14.7,
        "ethanol_pct": 0.0,
        "combustion_efficiency": 0.85,
        # --- Механика и зазоры ---
        "piston_mass_g": 220,
        "conrod_length_mm": 95,
        "bearing_clearance_um": 15,
        "piston_cylinder_clearance_um": 25,
        "piston_ring_tension_N": 18,
        "governor_max_rpm": 13500,
        "idle_rpm": 2800,
        "throttle_tau_s": 0.12,
        # --- Цепь и резка ---
        "sprocket_teeth": 6,
        "chain_pitch_mm": 3.25,
        "guide_bar_len_cm": 40,
        "chain_tension_N": 45,
        "cutting_load": 0.0,
        "chain_wear_factor": 0.0,
        # --- Акустика и среда ---
        "housing_resonance_hz": 320,
        "housing_damping": 0.15,
        "ambient_temp_c": 20.0,
        "air_pressure_kpa": 101.3,
        "mic_distance_m": 1.0,
        "directional_gain_db": 3.0,
    }

    def __init__(self, **overrides):
        self.params = self.DEFAULT_PARAMS.copy()
        self.params.update(overrides)
        self._validate_params()
        self.sr = None

    def _validate_params(self):
        p = self.params
        if p["compression_ratio"] < 6.0 or p["compression_ratio"] > 13.0:
            raise ValueError("Compression ratio must be 6.0-13.0 for 2-stroke saws")
        if p["air_fuel_ratio"] < 10.0 or p["air_fuel_ratio"] > 18.0:
            raise ValueError("AFR out of realistic range")
        if p["cutting_load"] < 0.0 or p["cutting_load"] > 1.0:
            raise ValueError("Cutting load must be 0.0-1.0")

    def _rpm_profile(self, duration, sr, throttle_position=1.0):
        """Простая динамика оборотов для стриминга"""
        t = np.arange(0, duration, 1.0 / sr)
        target = (
            self.params["idle_rpm"]
            + (self.params["governor_max_rpm"] - self.params["idle_rpm"]) * throttle_position
        )
        tau = self.params["throttle_tau_s"] * (1.0 + 0.5 * self.params["cutting_load"])
        rpm = target - (target - self.params["idle_rpm"]) * np.exp(-t / tau)
        
        # Добавляем небольшую модуляцию от нагрузки
        droop = self.params["cutting_load"] * 1200.0 * np.sin(2 * np.pi * 0.5 * t)
        rpm += droop
        
        return t, np.clip(rpm, self.params["idle_rpm"] - 200, self.params["governor_max_rpm"])

    def _combustion_signal(self, t, rpm, sr):
        """Импульсы сгорания + гармоники"""
        p = self.params
        phase = np.zeros_like(t)
        phase[1:] = phase[:-1] + (rpm[:-1] / 60.0) * (t[1] - t[0])
        phase %= 1.0

        fire_mask = (phase[:-1] < 0.02) & (phase[1:] >= 0.02)
        fire_idx = np.where(fire_mask)[0]
        if len(fire_idx) == 0:
            fire_idx = np.array([0])

        rise_time = 0.8e-3 / (1.0 + (p["compression_ratio"] - 8.0) * 0.1)
        decay_time = 4.5e-3 * (1.0 + 0.3 * p["oil_ratio_50_1"])
        fuel_eff = p["combustion_efficiency"] * (p["fuel_octane"] / 90.0)

        sig = np.zeros_like(t)
        for idx in fire_idx:
            if idx >= len(t) - 100:
                continue
            dt = np.arange(0, 12e-3, 1.0 / sr)
            pulse = np.exp(-((dt / rise_time) ** 2)) * np.exp(-dt / decay_time)
            pulse *= fuel_eff * (p["bore_mm"] / 40.0) ** 2
            end = min(idx + len(pulse), len(t))
            sig[idx:end] += pulse[: end - idx]

        n_harmonics = 40
        spectral_rolloff = (
            1.2
            + 0.4 * (p["air_fuel_ratio"] - 14.0) ** 2
            + 0.2 * p["ethanol_pct"] / 10.0
        )
        harm_signal = np.zeros_like(t)

        for n in range(1, n_harmonics + 1):
            f_n_max = (np.max(rpm) / 60.0) * n
            if f_n_max > sr / 2:
                break
            f_n = (rpm / 60.0) * n
            amp = sig * (1.0 / (n**spectral_rolloff)) * np.sin(2 * np.pi * f_n * t)
            harm_signal += amp * 0.15

        return sig * 0.6 + harm_signal

    def _mechanical_noise(self, t, rpm, sr):
        """Шум КШМ, подшипников, поршневых колец"""
        p = self.params
        noise = np.random.randn(len(t))
        clearance_factor = (p["bearing_clearance_um"] / 15.0) ** 1.3 * (
            p["piston_cylinder_clearance_um"] / 25.0
        ) ** 0.8
        mass_factor = (p["piston_mass_g"] / 220.0) ** 0.7

        amp = 0.08 * clearance_factor * mass_factor * (rpm / 8000.0) ** 1.8
        amp = np.clip(amp, 0.0, 0.5)

        rpm_mean = np.mean(rpm)
        f_mech = 120.0 + 80.0 * (rpm_mean / 10000.0)
        Q = 2.5 + 1.5 * (p["conrod_length_mm"] / 95.0)

        f_low = max(20.0, f_mech / Q)
        f_high = min(sr / 2 - 100, f_mech * Q)

        sos = butter(
            2, [f_low / (sr / 2), f_high / (sr / 2)], btype="bandpass", output="sos"
        )
        noise_filt = sosfilt(sos, noise)

        return noise_filt * amp

    def _chain_noise(self, t, rpm, sr):
        """Звук цепи: зацепление, трение, резонанс шины"""
        p = self.params
        f_tooth = (rpm / 60.0) * p["sprocket_teeth"]
        phase = np.mod(np.cumsum(f_tooth / sr), 1.0)
        tooth_imp = np.exp(-(((phase - 0.01) / 0.005) ** 2))

        base_f_res = 800.0
        f_res = (
            base_f_res
            * np.sqrt(p["chain_tension_N"] / 45.0)
            * (1.0 + 0.4 * p["chain_wear_factor"])
        )
        Q_chain = 4.0 - 2.0 * p["chain_wear_factor"]

        sos_chain = butter(
            2,
            [f_res / (sr / 2) / Q_chain, f_res / (sr / 2) * Q_chain],
            btype="bandpass",
            output="sos",
        )
        chain_sig = sosfilt(sos_chain, tooth_imp)

        friction = np.random.randn(len(t))
        friction_amp = (
            0.06
            * (1.0 + 1.5 * p["cutting_load"])
            * (p["guide_bar_len_cm"] / 40.0) ** 0.5
        )
        sos_fr = butter(
            3, [2000 / (sr / 2), 8000 / (sr / 2)], btype="bandpass", output="sos"
        )
        friction = sosfilt(sos_fr, friction) * friction_amp

        return chain_sig * 0.4 + friction

    def _apply_acoustic_filters(self, signal, sr):
        """Глушитель, корпус, затухание в воздухе"""
        p = self.params
        f_cutoff = 1800.0 * (p["muffler_volume_cm3"] / 850.0) ** -0.33
        sos_muf = butter(4, f_cutoff / (sr / 2), "low", output="sos")
        signal = sosfilt(sos_muf, signal)

        f_hous = p["housing_resonance_hz"]
        Q_hous = 3.0 * (1.0 - p["housing_damping"])
        sos_hous = butter(
            2,
            [f_hous / (sr / 2) / Q_hous, f_hous / (sr / 2) * Q_hous],
            btype="bandpass",
            output="sos",
        )
        signal += sosfilt(sos_hous, signal) * 0.12

        f_high = 4000.0
        sos_air = butter(1, f_high / (sr / 2), "low", output="sos")
        signal = sosfilt(sos_air, signal) * (1.0 / (p["mic_distance_m"] ** 0.6))

        signal *= 10 ** (p["directional_gain_db"] / 20.0)
        return signal

    def generate_chunk(self, duration=0.1, sr=44100, throttle_position=1.0):
        """Генерация короткого аудио-чанка для стриминга"""
        self.sr = sr
        t, rpm = self._rpm_profile(duration, sr, throttle_position)

        comb = self._combustion_signal(t, rpm, sr)
        mech = self._mechanical_noise(t, rpm, sr)
        chain = self._chain_noise(t, rpm, sr)

        mix = comb * 0.7 + mech * 0.5 + chain * 0.6
        mix = self._apply_acoustic_filters(mix, sr)

        peak = np.max(np.abs(mix))
        if peak > 0.0:
            mix *= 0.92 / peak

        mix = np.clip(mix, -1.0, 1.0).astype(np.float32)
        return mix, np.mean(rpm)

    def audio_to_wav_bytes(self, audio_data, sr):
        """Конвертация numpy массива в WAV байты"""
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sr)
            wav_file.writeframes(audio_int16.tobytes())
        
        return buffer.getvalue()
