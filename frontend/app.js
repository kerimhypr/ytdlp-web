const $ = (selector) => document.querySelector(selector);
const state = { url: "", info: null, timer: null };

const formats = {
  audio: [["best", "Best / Orijinal"], ["mp3", "MP3"], ["opus", "OPUS"], ["flac", "FLAC"], ["wav", "WAV"]],
  video: [["best", "Best / Orijinal"], ["mp4-1080", "MP4 · 1080p"], ["mp4-720", "MP4 · 720p"], ["mp4-480", "MP4 · 480p"]],
  subtitle: [["srt", "SRT"], ["vtt", "VTT"]]
};

function setError(message = "") { $("#error").textContent = message; }
function populateFormats() { $("#format").innerHTML = formats[$("#kind").value].map(([value, text]) => `<option value="${value}">${text}</option>`).join(""); }
function time(value) { if (!value) return "—"; const sec = Math.round(value); return `${String(Math.floor(sec / 60)).padStart(2,"0")}:${String(sec % 60).padStart(2,"0")}`; }

$("#kind").addEventListener("change", populateFormats); populateFormats();
$("#inspect-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setError(""); const button = event.target.querySelector("button"); button.disabled = true; button.textContent = "İnceleniyor...";
  try { const url = $("#url").value; const response = await fetch("/api/inspect", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url}) }); const data = await response.json(); if (!response.ok) throw Error(data.detail || "Link çözümlenemedi"); state.url = url; state.info = data; $("#thumbnail").src = data.thumbnail || ""; $("#title").textContent = data.title; $("#uploader").textContent = data.uploader || "UNKNOWN CREATOR"; $("#duration").textContent = time(data.duration); $("#source").textContent = new URL(url).hostname.replace("www.","").toUpperCase(); $("#target-url").textContent = data.webpage_url || url; $("#result").classList.remove("hidden"); $("#result").scrollIntoView({behavior:"smooth", block:"start"}); } catch (error) { setError(error.message); } finally { button.disabled = false; button.innerHTML = "FETCH <span>↗</span>"; }
});

$("#download").addEventListener("click", async () => {
  setError(""); const button = $("#download"); button.disabled = true; $("#progress-area").classList.remove("hidden"); $("#progress-label").textContent = "Kuyruğa alındı...";
  try { const response = await fetch("/api/download", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url:state.url, kind:$("#kind").value, format:$("#format").value, start:$("#start").value || null, end:$("#end").value || null}) }); const data = await response.json(); if (!response.ok) throw Error(data.detail || "İndirme başlatılamadı"); poll(data.job_id); } catch (error) { setError(error.message); button.disabled = false; }
});

function poll(jobId) { clearInterval(state.timer); state.timer = setInterval(async () => { const response = await fetch(`/api/download/${jobId}`); const job = await response.json(); $("#progress-value").textContent = `${job.progress || 0}%`; $("#progress-bar").style.width = `${job.progress || 0}%`; $("#progress-label").textContent = job.status === "complete" ? "Hazır — indirme başlıyor" : job.status === "error" ? "İşlem başarısız" : "İşleniyor..."; if (job.status === "complete") { clearInterval(state.timer); window.location.href = job.download_url; $("#download").disabled = false; } if (job.status === "error") { clearInterval(state.timer); setError(job.error || "İşlem başarısız"); $("#download").disabled = false; } }, 700); }
