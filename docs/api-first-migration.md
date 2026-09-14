API-FIRST REELKIT MIGRATION DESIGN (research snapshot 2026-09-14)

Current measured compute profile
- Reference v48 (32.47s output, Kaggle CPU, 2 render workers): scaffold 104.3s, build 10.2s, segmented frame-render+encode+mix+export 622.9s. The end-to-end measured portion is 737.4s, so render path is 84.5%, scaffold 14.1%, build 1.4%. The earlier 47s benchmark transcribed locally on Kaggle in 88s. Planning is deterministic/local in current pipeline and small compared with rendering.
- Within a measured 8.5s segment: capture 49.3s, H.264 encode 22.3s, assemble 1.2s, total 79.6s. Thus capture 62%, encode 28%, assemble 1.5%, other init 8.5%. Extrapolating the same shape to v48's 622.9s render: ~386s frame capture, ~174s encode, ~9s assembly, ~54s startup/other.
- Audio mix is FFmpeg CPU and tiny relative to frame capture. The v48 logs show four cues, iterative audibility lift, ducking, join, and export after capture; there is no GPU work.
- Local encode control: a 76.2s 478x850 clip re-encoded H.264/AAC in 22.8s wall, 44.5 CPU-seconds, 152MB max RSS (3.34x realtime). This confirms encoding is ordinary CPU work; the expensive path is browser frame capture at 1080x1920.
- Current Kaggle run is CPU only. No stage needs GPU. Whisper currently downloads/runs a local model and is the easiest stage to externalize.

Target architecture
1. Upload/source service stores original and creates job record.
2. OpenAI Agents SDK orchestrator owns the durable run. OpenAI docs say the SDK runs repeated tool calls/branching, supports sessions, tracing, guardrails, human review and resumable approvals. Use function tools for transcribe, plan validation, render submission/status, artifact fetch, vision QC, and final publish-to-review. The Responses API is the lower-level alternative if Reelkit wants to own every loop; SDK better matches the requested resumable QC loop.
3. Transcription tool calls OpenAI gpt-transcribe/gpt-4o-transcribe or Deepgram Nova-3 multilingual. Require word timestamps and Hebrew; run an A/B transcript accuracy test before choosing. Deepgram pre-recorded multilingual is $0.0052/min; OpenAI gpt-transcribe is $0.0045/min, gpt-4o-transcribe ~$0.006/min.
4. Plan agent calls the chosen current OpenAI planning model with the transcript, Reelkit schema and brand/style constraints. Note: public docs currently list GPT-5.4/5.6, not a public model named GPT-6. Treat "GPT-6" as the requested logical planner slot until the account exposes an exact API model ID. Validate output through Reelkit lint before render.
5. Renderer tool enqueues a CPU job on Railway. The worker runs existing Docker image, Chromium/HyperFrames, FFmpeg, geometry and SFX gates. Return progress and artifact URLs; do not hold one synchronous HTTP request open. One job per worker initially, hard 2-vCPU/4GB limit, 20-minute app timeout, object storage for source/output, then measure.
6. Vision QC loop extracts 8-15 key frames plus geometry report, sends them to a vision-capable OpenAI model, and allows bounded plan patches (maximum two rerenders). Structural gates remain deterministic and cannot be overridden by vision. Human review remains the final publishing gate.

Railway fit
- Hobby is $5/month and the base fee counts toward usage. Current docs list ceilings up to 48GB RAM/48 vCPU, 100GB ephemeral storage, 5GB volume storage and 100GB image size for Hobby. Those are ceilings, not prepaid allocations.
- Usage prices: $20/vCPU-month ($0.000463/vCPU-minute), $10/GB-month ($0.000231/GB-minute), egress $0.05/GB. Billing is by actual minute. Serverless sleeps after 10 minutes without outbound traffic, but a queue worker/polling connection can keep it awake. Build as an on-demand worker or explicitly scale to zero when idle.
- A 2-minute output at v48's ~19.2x-realtime full render rate is ~38 minutes on the observed Kaggle CPU. That is too long for a request/response handler but fine for an asynchronous Railway worker if app-level timeout is >=45 minutes. Railway docs expose resource ceilings and billing, not a short per-request compute cap. Memory should fit 4GB based on 2 concurrent Chromium renderers plus FFmpeg, but this is an engineering estimate; deploy a benchmark before promising throughput.
- Cost estimate for an active 2-vCPU/4GB worker for 38 minutes: CPU $0.035 + RAM $0.035 = ~$0.070/render, plus egress (a 30MB output is ~$0.0015). At 3 renders/day: ~$6.3 usage/month, so total is about $6-8/month because the $5 Hobby subscription is included in usage, not added on top. If an always-on service idles at 0.3GB and 0.05 vCPU, baseline is ~$4/month and still inside the $5 minimum. At 5/day, compute estimate ~$10.5/month before API costs.

Per-render API estimate (2-minute video)
- Transcription: $0.009 gpt-transcribe, $0.012 gpt-4o-transcribe, or $0.0104 Deepgram Nova-3 multilingual.
- Planning: exact tokens/model are unmeasured. At current GPT-5.4 public rates ($2.50/M input, $15/M output), a conservative 20k input + 5k output costs $0.125. A lean 10k + 3k costs $0.070. "GPT-6" price cannot be claimed until a public model and rate exist.
- Vision QC: depends on model/image-tokenization. Budget $0.02-$0.10 for 8-15 compressed key frames and a short result; instrument actual usage. Two rerender loops multiply render and QC cost, not transcription.
- Railway render: ~$0.07 at measured current speed for 2 minutes.
- Expected single-pass total: roughly $0.17-$0.31/render (transcription $0.01 + planning $0.07-$0.125 + QC $0.02-$0.10 + Railway ~$0.07). Add storage/egress pennies. This excludes optional generated visual assets.

Alternatives
- Remotion Lambda: official docs say pay only while rendering, multiple minutes often cost pennies, 15-minute Lambda timeout and 10GB temp storage. It can parallelize standard Remotion compositions. Reelkit is HyperFrames/Playwright plus custom geometry/audio gates, so adopting Lambda is not a drop-in host; it is a renderer rewrite or compatibility project.
- Modal/RunPod CPU: technically fit as pay-per-job CPU workers and avoid idle cost, but no current price is quoted here because the requested target is Railway and pricing must be verified for the chosen CPU size/region at implementation time.
- fal.ai Whisper: possible hosted transcription route, but OpenAI/Deepgram have clearer public per-minute prices and direct Hebrew-capable products. Benchmark accuracy and word timestamps, not just price.

Migration order, no production changes yet
A. Add timing/CPU/RSS metrics around all stages and capture a 30s/60s/120s benchmark set.
B. Add provider-neutral transcription interface; A/B OpenAI vs Deepgram on Hebrew walking audio.
C. Wrap the current renderer as one idempotent job endpoint using content hashes and existing checkpoints; deploy a private Railway benchmark only after user approves the $5 plan.
D. Add Agents SDK orchestration and tool contracts; keep render tool asynchronous and resumable.
E. Add vision QC with a two-loop cap and non-overridable deterministic gates.
F. Shadow-run against Kaggle for 10 reels; switch after quality, time and cost deltas are measured.

Sources
https://docs.railway.com/pricing/plans
https://docs.railway.com/pricing
https://docs.railway.com/guides/right-size-cpu-memory
https://platform.openai.com/docs/guides/agents
https://platform.openai.com/docs/guides/tools
https://developers.openai.com/api/docs/pricing
https://deepgram.com/pricing
https://www.remotion.dev/docs/lambda
