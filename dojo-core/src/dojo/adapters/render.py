from __future__ import annotations

import subprocess
from pathlib import Path

from dojo.exceptions import RenderFailed
from dojo.model import ReelBuild

CANVAS_W = 1080
CANVAS_H = 1920
FPS = 25
AUDIO_RATE = 44100


def _probe_has_audio(path: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _probe_is_video(path: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


class FfmpegReelRenderer:
    """Render an immutable 1080x1920 Reel: blurred fit, clip audio, watermark."""

    def render(self, build: ReelBuild, work_dir: Path, out_path: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        segments: list[Path] = []
        try:
            if build.intro_asset is not None:
                segments.append(
                    self._render_segment(
                        build.intro_asset,
                        is_video=_probe_is_video(build.intro_asset),
                        duration=build.intro_duration or build.photo_duration,
                        logo_asset=build.logo_asset,
                        work_dir=work_dir,
                        name="intro",
                    )
                )
            for clip in build.clips:
                segments.append(
                    self._render_segment(
                        clip.path,
                        is_video=clip.is_video,
                        duration=clip.duration,
                        trim_start=clip.trim_start,
                        trim_end=clip.trim_end,
                        logo_asset=build.logo_asset,
                        work_dir=work_dir,
                        name=clip.media_id,
                    )
                )
            if build.outro_asset is not None:
                segments.append(
                    self._render_segment(
                        build.outro_asset,
                        is_video=_probe_is_video(build.outro_asset),
                        duration=build.outro_duration or build.photo_duration,
                        logo_asset=build.logo_asset,
                        work_dir=work_dir,
                        name="outro",
                    )
                )
            self._concat(segments, out_path)
            self._assert_canvas(out_path)
        except RenderFailed:
            raise
        except Exception as exc:
            raise RenderFailed(f"reel render failed: {exc}") from exc
        return out_path

    def _render_segment(
        self,
        source: Path,
        *,
        is_video: bool,
        duration: float,
        logo_asset: Path | None,
        work_dir: Path,
        name: str,
        trim_start: float = 0.0,
        trim_end: float | None = None,
    ) -> Path:
        if not source.is_file():
            raise RenderFailed(f"render source missing: {source}")
        seg = work_dir / f"{name}.mp4"
        logo_args = ["-i", str(logo_asset)] if logo_asset is not None else []
        input_args = (
            ["-loop", "1", "-framerate", str(FPS)] if not is_video else []
        )

        has_audio = _probe_has_audio(source)
        audio_map: list[str] = []
        if has_audio:
            audio_map = ["-map", "0:a"]
        else:
            silent_idx = 2 if logo_args else 1
            audio_map = ["-map", f"{silent_idx}:a"]

        if is_video and trim_end is not None:
            duration_args = ["-ss", f"{trim_start:.3f}",
                             "-t", f"{trim_end - trim_start:.3f}"]
        elif not is_video and trim_start > 0:
            duration_args = ["-ss", f"{trim_start:.3f}", "-t", f"{duration:.3f}"]
        else:
            duration_args = ["-t", f"{duration:.3f}"]

        filter_complex = (
            f"[0:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,crop={CANVAS_W}:{CANVAS_H},"
            "boxblur=luma_radius=20:luma_power=2:chroma_radius=20:chroma_power=2[bg];"
            f"[0:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
        )
        out_chain = "[base]"
        if logo_args:
            filter_complex += (
                ";[1:v]overlay=W-w-48:H-h-48:format=auto[vout]"
            )
            out_chain = "[vout]"
        command = ["ffmpeg", "-y"]
        if not has_audio:
            command += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i",
                        f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}"]
        command += [*input_args, "-i", str(source), *logo_args,
                    "-filter_complex", filter_complex,
                    "-map", out_chain, *audio_map,
                    "-r", str(FPS), *duration_args,
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                    "-movflags", "+faststart", str(seg)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 or not seg.is_file():
            raise RenderFailed(
                f"segment render failed: {result.stderr.strip()[:200]}"
            )
        return seg

    def _concat(self, segments: list[Path], out_path: Path) -> None:
        if not segments:
            raise RenderFailed("no clips to render")
        list_file = out_path.parent / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in segments) + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not out_path.is_file():
            raise RenderFailed(
                f"reel concat failed: {result.stderr.strip()[:200]}"
            )

    def _assert_canvas(self, path: Path) -> None:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RenderFailed(
                f"could not probe reel: {result.stderr.strip()[:200]}"
            )
        width, height = result.stdout.split(",")
        if int(width) != CANVAS_W or int(height) != CANVAS_H:
            raise RenderFailed(
                f"reel is {width}x{height}, expected {CANVAS_W}x{CANVAS_H}"
            )