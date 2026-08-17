# ytdlp-web

Stateless, tek konteynerli medya çıkarıcı. FastAPI, yt-dlp ve ffmpeg kullanır; veritabanı yoktur.

## Çalıştırma

```bash
docker build -t ytdlp-web .
docker run --rm -p 8000:8000 ytdlp-web
```

Ardından `http://localhost:8000` adresini açın. Render, `render.yaml` ve `Dockerfile` üzerinden otomatik çalışır.

## API

- `GET /api/health` — servis sağlık kontrolü
- `POST /api/inspect` — `{ "url": "https://..." }` ile metadata/thumbnail/duration döndürür
- `POST /api/download` — `url`, `kind` (`audio|video|subtitle`), `format`, isteğe bağlı `start`/`end` alır; `job_id` döndürür
- `GET /api/download/{job_id}` — progress ve durum polling endpoint’i
- `GET /api/download/{job_id}/file` — tamamlanan geçici dosyayı indirir ve temizler

Desteklenen formatlar ses için `best`, `mp3`, `opus`, `flac`, `wav`; video için `best`, `mp4-1080`, `mp4-720`, `mp4-480`; altyazı için `srt`, `vtt` şeklindedir.
