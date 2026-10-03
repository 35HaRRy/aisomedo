# Synthetic timeline fixture

`timeline.mp4`: generated solid-color test content, 30 seconds, 160×90,
25 fps, H.264/yuv420p with AAC sine-wave audio; no dojo/user media.

Generated with `jrottenberg/ffmpeg:8-alpine`:

```text
ffmpeg -y -f lavfi -i color=c=teal:s=160x90:d=30:r=25
  -f lavfi -i sine=frequency=440:duration=30 -c:v libx264
  -pix_fmt yuv420p -c:a aac -movflags +faststart timeline.mp4
```
