# app.py
import streamlit as st
import streamlit.components.v1 as components
import base64, tempfile, os, io, json
from pathlib import Path
import requests

st.set_page_config(page_title="Voice → AI → Voice", layout="centered")
st.title("🎤 Voice → AI → Voice (Streamlit)")

# -----------------------
# Helper: embed a small HTML/JS audio recorder
# (returns base64 WAV data)
# -----------------------
RECORDER_HTML = """
<style>
button.record-btn { font-size:16px; padding:10px 18px; border-radius:8px;}
button.stop-btn { background:#e63946; color:white; padding:8px 14px; border-radius:8px;}
</style>
<div id="recorder">
  <button id="record" class="record-btn">🎙️ Start Recording</button>
  <button id="stop" class="stop-btn" disabled>⏹ Stop</button>
  <p id="status"></p>
</div>
<script>
const recordButton = document.getElementById('record');
const stopButton = document.getElementById('stop');
const status = document.getElementById('status');

let mediaRecorder;
let audioChunks = [];

recordButton.onclick = async () => {
  if (!navigator.mediaDevices) {
    status.innerText = 'getUserMedia not supported in this browser.';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks, { type: 'audio/wav' });
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64data = reader.result.split(',')[1];
        // send to streamlit
        const payload = { audio_base64: base64data };
        // use Streamlit setComponentValue (works in components)
        window.parent.postMessage({ type: 'STREAMLIT_AUDIO', value: payload }, '*');
      };
      reader.readAsDataURL(blob);
    };
    mediaRecorder.start();
    status.innerText = 'Recording...';
    recordButton.disabled = true;
    stopButton.disabled = false;
  } catch (err) {
    status.innerText = 'Permission denied or error: ' + err;
  }
};

stopButton.onclick = () => {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
    status.innerText = 'Processing audio...';
  }
  recordButton.disabled = false;
  stopButton.disabled = true;
};
</script>
"""

# create a simple component that listens for postMessage to get recorder output
components.html(RECORDER_HTML, height=180)

# Listen for messages posted by the component
# Streamlit doesn't provide a direct message listener, so we read window.postMessage via component return
# We'll use a tiny trick: a second HTML block that posts the recorded base64 into a known <input> via JS.
# But simpler: use Streamlit experimental get_query_params hack isn't reliable. So instead use
# streamlit_javascript component style would be ideal; for brevity, we accept audio upload alternative if not captured.

st.info("If the recorder did not return audio, please use 'Upload audio' fallback below.")

# Fallback file uploader
uploaded_file = st.file_uploader("Or upload a .wav/.mp3 file", type=['wav', 'mp3', 'm4a', 'ogg'])

# We attempt to capture messages from the embedded recorder using Streamlit's experimental component value:
# (when the recorder finishes it posts a message; Streamlit may surface that in `st.experimental_get_query_params` in some environments.
# To keep this robust, if the recorder doesn't return audio we'll rely on the uploader.)
#
# In many Streamlit deployments, you can replace this with an official component like `streamlit-webrtc` or a maintained audio-recorder component.

# -----------------------
# When we have an audio (uploaded) -> process it
# -----------------------
def save_base64_audio_to_file(b64, out_path):
    audio_bytes = base64.b64decode(b64)
    with open(out_path, "wb") as f:
        f.write(audio_bytes)
    return out_path

def call_stt_api(local_file_path):
    """
    Replace this with your STT provider. Example: OpenAI Whisper endpoint or AssemblyAI.
    This function should return the transcribed text as a string.
    """
    st.info("Sending audio to STT API...")
    # Example: send audio file to an HTTP endpoint
    STT_ENDPOINT = st.secrets.get("https://eastasia.api.cognitive.microsoft.com/", None)
    STT_KEY = st.secrets.get("1f9hcUtjhvtdUv2nhtebXYAQ2SaWu8MjEyrZ0hH37jw1n4ETfgXVJQQJ99BKAC3pKaRXJ3w3AAAYACOG3AV4", None)
    if not STT_ENDPOINT or not STT_KEY:
        st.error("STT endpoint/key not configured. Check .streamlit/secrets.toml.")
        return ""
    files = {"file": open(local_file_path, "rb")}
    headers = {"Authorization": f"Bearer {STT_KEY}"}
    resp = requests.post(STT_ENDPOINT, headers=headers, files=files, timeout=120)
    if resp.status_code != 200:
        st.error(f"STT API error: {resp.status_code} {resp.text}")
        return ""
    data = resp.json()
    # adapt to your API's response format
    return data.get("text") or data.get("transcript") or data.get("result") or ""

def call_llm_api(user_text):
    """
    Replace this with your LLM provider request (OpenAI, or others).
    Return LLM reply text.
    """
    st.info("Sending text to LLM...")
    LLM_ENDPOINT = st.secrets.get("https://eastasia.api.cognitive.microsoft.com/", None)
    LLM_KEY = st.secrets.get("1f9hcUtjhvtdUv2nhtebXYAQ2SaWu8MjEyrZ0hH37jw1n4ETfgXVJQQJ99BKAC3pKaRXJ3w3AAAYACOG3AV4", None)
    if not LLM_ENDPOINT or not LLM_KEY:
        st.error("LLM endpoint/key not configured. Check .streamlit/secrets.toml.")
        return ""
    headers = {"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"}
    payload = {"prompt": user_text, "max_tokens": 512}
    resp = requests.post(LLM_ENDPOINT, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        st.error(f"LLM API error: {resp.status_code} {resp.text}")
        return ""
    data = resp.json()
    # adapt to provider: try common fields
    if "choices" in data and len(data["choices"])>0:
        return data["choices"][0].get("text") or data["choices"][0].get("message", {}).get("content","")
    return data.get("response") or data.get("text") or ""

def call_tts_api(text, out_path):
    """
    Replace with your TTS provider HTTP call.
    Save result audio to out_path (mp3/wav) and return out_path.
    """
    st.info("Requesting TTS audio...")
    TTS_ENDPOINT = st.secrets.get("https://eastasia.api.cognitive.microsoft.com/", None)
    TTS_KEY = st.secrets.get("1f9hcUtjhvtdUv2nhtebXYAQ2SaWu8MjEyrZ0hH37jw1n4ETfgXVJQQJ99BKAC3pKaRXJ3w3AAAYACOG3AV4", None)
    if not TTS_ENDPOINT or not TTS_KEY:
        st.error("TTS endpoint/key not configured. Check .streamlit/secrets.toml.")
        return None
    headers = {"Authorization": f"Bearer {TTS_KEY}", "Content-Type": "application/json"}
    payload = {"text": text, "voice": st.secrets.get("TTS_VOICE","default")}
    resp = requests.post(TTS_ENDPOINT, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        st.error(f"TTS API error: {resp.status_code} {resp.text}")
        return None
    # assume binary audio returned
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path

# -----------------------
# Main button to process (if uploader provided)
# -----------------------
if st.button("Process audio (STT → LLM → TTS)"):
    # We see if the embed recorded audio posted to parent; attempt to read from query params or uploader
    # Fallback: use uploaded file
    audio_path = None
    if uploaded_file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp:
            tmp.write(uploaded_file.read())
            audio_path = tmp.name

    if not audio_path:
        st.warning("No audio available. Use the recorder (top) or upload a file.")
    else:
        # 1) STT
        user_text = call_stt_api(audio_path)
        if not user_text:
            st.error("No transcription returned.")
        else:
            st.markdown("**You said:**")
            st.info(user_text)

            # 2) LLM
            ai_reply = call_llm_api(user_text)
            if not ai_reply:
                st.error("LLM didn't return a reply.")
            else:
                st.markdown("**AI reply:**")
                st.success(ai_reply)

                # 3) TTS - generate audio
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_out:
                    out_path = audio_out.name
                tts_file = call_tts_api(ai_reply, out_path)
                if tts_file:
                    st.audio(tts_file)
                    st.balloons()
                else:
                    st.error("TTS failed.")

# -----------------------
# Show secrets helper (only non-empty keys masked)
# -----------------------
if st.checkbox("Show configured APIs (keys masked)"):
    st.write({
        "STT_ENDPOINT": bool(st.secrets.get("STT_ENDPOINT")),
        "LLM_ENDPOINT": bool(st.secrets.get("LLM_ENDPOINT")),
        "TTS_ENDPOINT": bool(st.secrets.get("TTS_ENDPOINT")),
    })
