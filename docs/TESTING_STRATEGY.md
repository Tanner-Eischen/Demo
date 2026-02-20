# TESTING_STRATEGY — vo-demo-generator (MVP)

## Test matrix

| Component | Unit | Integration | E2E |
|---|---|---|---|
| project persistence | read/write, schema validate | create project directory | upload -> run -> artifacts exist |
| segmentation | clamp/merge/split logic | ffprobe + ffmpeg scene output parsing | run on short fixture mp4 |
| keyframes | timestamp mapping | ffmpeg extraction smoke | included in E2E |
| vision (optional) | schema validate + retry policy | mock Z.ai responses | E2E with mocks |
| rewrite (optional) | word budget logic | mock GLM-5 | E2E with mocks |
| tts (optional) | duration measurement | mock endpoint / silence fallback | E2E (silence mode) |
| mux | filter script generation | ffmpeg mix/mux smoke | validate final streams exist |

## CI Suggestions
- Run unit + integration on every push
- Run E2E on a tiny fixture video (<= 5s) or nightly

## Local QA checklist
- Can upload and create project
- Can run pipeline twice (second run reuses artifacts)
- project.json remains valid against schema
- final.mp4 plays and has an audio track
- script.srt lines match segment timings
