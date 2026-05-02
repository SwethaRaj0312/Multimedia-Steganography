import streamlit as st
import tempfile
import time
import numpy as np
import wave
import random
import hashlib
import base64
from math import log10
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from cryptography.fernet import Fernet

# =========================
# KEY + POSITIONS
# =========================
def generate_key(password):
    hashed = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(hashed)

def generate_positions(password, total):
    seed = int(hashlib.sha256(password.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    pos = list(range(total))
    rng.shuffle(pos)
    return np.array(pos)

# =========================
# METRICS (SAFE)
# =========================
def mse(a, b):
    return np.mean((a - b) ** 2)

def snr(a, b):
    noise = a - b
    signal_power = np.mean(a.astype(np.float64)**2)
    noise_power = np.mean(noise.astype(np.float64)**2)

    if noise_power <= 1e-10:
        return float('inf')

    return 10 * log10(signal_power / noise_power)

def psnr(a, b):
    m = mse(a, b)
    if m <= 1e-10:
        return float('inf')
    return 20 * log10(32767) - 10 * log10(m)

def calculate_ber(original_bits, extracted_bits):
    if not original_bits or not extracted_bits:
        return 0
    length = min(len(original_bits), len(extracted_bits))
    orig = np.array(list(original_bits[:length]), dtype=np.uint8)
    ext = np.array(list(extracted_bits[:length]), dtype=np.uint8)
    return np.sum(orig != ext) / length

# =========================
# EMBEDDING (VECTORIZED)
# =========================
def embed(video_file, text_file, password):
    try:
        temp_video = tempfile.NamedTemporaryFile(delete=False)
        temp_video.write(video_file.read())
        temp_video.close()

        secret = text_file.read().decode()

        key = generate_key(password)
        cipher = Fernet(key)

        start_enc = time.time()
        enc = cipher.encrypt(secret.encode()) + b"#####"
        end_enc = time.time()

        binary = ''.join(format(b, '08b') for b in enc)

        video = VideoFileClip(temp_video.name)

        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
        video.audio.write_audiofile(temp_audio, codec="pcm_s16le", logger=None)

        audio = wave.open(temp_audio, 'rb')
        frames = bytearray(audio.readframes(audio.getnframes()))

        capacity_percent = (len(binary) / len(frames)) * 100

        if len(binary) > len(frames):
            return None, None, "Data too large"

        frames_np = np.frombuffer(frames, dtype=np.uint8)
        pos = generate_positions(password, len(frames_np))[:len(binary)]
        bits = np.array(list(binary), dtype=np.uint8)

        start_embed = time.time()
        frames_np[pos] = (frames_np[pos] & 254) | bits
        end_embed = time.time()

        stego_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
        out = wave.open(stego_audio, 'wb')
        out.setparams(audio.getparams())
        out.writeframes(frames_np.tobytes())
        audio.close()
        out.close()

        orig = np.frombuffer(wave.open(temp_audio, 'rb').readframes(-1), dtype=np.int16)
        stego = np.frombuffer(wave.open(stego_audio, 'rb').readframes(-1), dtype=np.int16)

        final_video_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mkv").name
        final = video.with_audio(AudioFileClip(stego_audio))
        final.write_videofile(final_video_path, codec="libx264", audio_codec="pcm_s16le", logger=None)

        metrics = {
            "MSE": float(mse(orig, stego)),
            "SNR": float(snr(orig, stego)),
            "PSNR": float(psnr(orig, stego)),
            "Capacity %": capacity_percent,
            "Embedding Time": end_embed - start_embed,
            "Encryption Time": end_enc - start_enc
        }

        return final_video_path, metrics, binary

    except Exception as e:
        return None, None, str(e)

# =========================
# EXTRACTION (VECTORIZED)
# =========================
def extract(video_file, password):
    try:
        temp_video = tempfile.NamedTemporaryFile(delete=False)
        temp_video.write(video_file.read())
        temp_video.close()

        video = VideoFileClip(temp_video.name)

        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
        video.audio.write_audiofile(temp_audio, codec="pcm_s16le", logger=None)

        audio = wave.open(temp_audio, 'rb')
        frames = bytearray(audio.readframes(audio.getnframes()))

        frames_np = np.frombuffer(frames, dtype=np.uint8)
        pos = generate_positions(password, len(frames_np))

        extracted_bits = frames_np[pos] & 1
        bit_string = ''.join(extracted_bits.astype(str))

        data = bytearray()
        byte = ""

        for bit in bit_string:
            byte += bit
            if len(byte) == 8:
                data.append(int(byte, 2))
                byte = ""
                if data[-5:] == b"#####":
                    break

        key = generate_key(password)
        cipher = Fernet(key)

        start = time.time()
        decrypted = cipher.decrypt(bytes(data[:-5]))
        end = time.time()

        extracted_binary = ''.join(format(b, '08b') for b in data[:-5])

        return decrypted.decode(), extracted_binary, end - start

    except Exception as e:
        return f"ERROR: {e}", "", 0

# =========================
# UI
# =========================
st.set_page_config(layout="wide")

st.title("🔐 An Enhanced Secure Communication Framework using Hybrid Multimedia Steganography")

tabs = st.tabs(["🔒 Embedding", "🔓 Extraction"])

# -------- EMBED --------
with tabs[0]:
    st.subheader("📥 Input")

    col1, col2 = st.columns(2)

    with col1:
        video_file = st.file_uploader("🎬 Upload Cover Video", type=["mp4", "mkv"])

    with col2:
        text_file = st.file_uploader("📄 Upload Secret Text", type=["txt"])
        password = st.text_input("🔑 Enter Password", type="password")

    if st.button("🚀 Start Encrypting & Embedding"):
        if video_file and text_file and password:

            with st.spinner("Processing... ⏳"):
                output, metrics, binary = embed(video_file, text_file, password)

            if output:
                st.session_state["original_bits"] = binary

                st.success("✅ Embedding Completed!")

                st.markdown("## 🎬 Video Comparison")
                c1, c2 = st.columns(2)

                with c1:
                    st.markdown("### Original Video")
                    st.video(video_file)

                with c2:
                    st.markdown("### Stego Video")
                    with open(output, "rb") as f:
                        st.video(f.read())

                st.markdown("## 📊 Metrics Dashboard")

                # FIRST ROW
                row1_col1, row1_col2, row1_col3 = st.columns(3)

                row1_col1.metric("MSE", f"{metrics['MSE']:.6f}")
                row1_col2.metric("SNR", "∞" if metrics["SNR"] == float('inf') else f"{metrics['SNR']:.2f} dB")
                row1_col3.metric("PSNR", "∞" if metrics["PSNR"] == float('inf') else f"{metrics['PSNR']:.2f} dB")

                # SECOND ROW
                row2_col1, row2_col2, row2_col3 = st.columns(3)

                row2_col1.metric("Capacity %", f"{metrics['Capacity %']:.2f}%")
                row2_col2.metric("Encryption Time", f"{metrics['Encryption Time']:.4f}s")
                row2_col3.metric("Embedding Time", f"{metrics['Embedding Time']:.4f}s")

                with open(output, "rb") as f:
                    st.download_button("⬇️ Download Stego Video", f, file_name="stego.mkv")

            else:
                st.error(metrics)

        else:
            st.warning("Provide all inputs")

# -------- EXTRACT --------
with tabs[1]:
    st.subheader("📤 Extraction")

    col1, col2 = st.columns(2)

    with col1:
        stego_video = st.file_uploader("Upload Stego Video", type=["mp4", "mkv"])

    with col2:
        password = st.text_input("Password", type="password", key="dec")

    if st.button("🚀 Start Extracting"):
        if stego_video and password:

            with st.spinner("Extract Processing... ⏳"):
                msg, extracted_bits, t = extract(stego_video, password)

            st.success("Recovered Successfully")

            st.text_area("Recovered Message", msg, height=200)

            row1_col1, row1_col2, row1_col3 = st.columns(3)

            row1_col1.metric("Decryption Time", f"{t:.4f}s")

            if "original_bits" in st.session_state:
                ber = calculate_ber(st.session_state["original_bits"], extracted_bits)
                accuracy = (1 - ber) * 100

                row1_col2.metric("Accuracy", f"{accuracy:.2f}%")
                row1_col3.metric("BER", f"{ber:.6f}")

        else:
            st.warning("Provide inputs")