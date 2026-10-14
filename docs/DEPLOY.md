# Deploying Am I Covered?

The app ships as **one Docker image**: FastAPI serves the API under `/api` and the built React app at `/`. The embedding models are baked into the image, and the vector index is rebuilt at startup (about 30 seconds for the federal rules + sample policy), so the container needs no external database.

Memory: about 1 GB is comfortable (three small ONNX models plus Qdrant). Hosts with 512 MB free tiers are too small.

## Option A: Hugging Face Spaces (free, recommended for a demo)

Free CPU Spaces have 2 vCPUs and 16 GB of RAM, which is plenty. A Space sleeps after a period of inactivity and wakes on the next visit (cold start ~1 minute).

1. Create an account at huggingface.co, then **New Space** → SDK **Docker** → *Blank* → visibility **Public**.
2. In the Space's **Settings → Variables and secrets**, add a **secret** `ANTHROPIC_API_KEY`.
3. Push this repository to the Space. The Space's `README.md` needs this front matter at the very top (Spaces reads it to know the port):

   ```yaml
   ---
   title: Am I Covered
   emoji: 🩺
   colorFrom: green
   colorTo: blue
   sdk: docker
   app_port: 7860
   ---
   ```

   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/am-i-covered
   git push space main
   ```

4. Watch the **Logs** tab. When you see `Application startup complete`, open the Space URL.

## Option B: any container host (Render, Railway, Fly.io, Google Cloud Run)

Point the host at the `Dockerfile` and set:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your key (as a secret) |
| `PORT` | usually set by the host automatically; defaults to 7860 |

Choose an instance with at least 1 GB of RAM. Uvicorn runs with `--proxy-headers`, so per-IP rate limits see real client IPs behind the host's load balancer.

## Option C: run the image yourself

```bash
docker build -t am-i-covered .
docker run -p 7860:7860 -e ANTHROPIC_API_KEY=sk-ant-... am-i-covered
# open http://localhost:7860
```

## Keeping uploads across restarts (optional)

By default the index lives inside the container, so uploads disappear on restart. That's acceptable because uploads expire after 24 hours anyway. To persist them, either mount a volume at `/app/backend/storage`, or create a free Qdrant Cloud cluster and set `QDRANT_URL` and `QDRANT_API_KEY`.

## Cost control checklist

- `QUESTIONS_PER_IP_PER_HOUR` (default 30) and `QUESTIONS_PER_DAY_GLOBAL` (default 600) cap spend. At roughly $0.03-0.06 per answered question (Claude Opus 5.5, medium effort), the default daily cap bounds a bad day at about $20-35. Lower it for a personal demo.
- Set a monthly spend limit in the Anthropic Console as a hard backstop.
- Off-topic questions are answered by the relevance gate without any LLM call.
