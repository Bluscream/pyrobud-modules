import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import telethon as tg

try:
    import speech_recognition as sr
except ModuleNotFoundError:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "SpeechRecognition", "audioop-lts"])
        import importlib
        importlib.invalidate_caches()
        import speech_recognition as sr
    except Exception as e:
        # Fallback if pip install fails
        sr = None
        pip_error = e

from pyrobud import command, module


def _get_ffmpeg_binary() -> str:
    # 1. System PATH
    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    # 2. imageio-ffmpeg if installed
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            try:
                if not os.path.exists("/usr/local/bin/ffmpeg"):
                    os.symlink(exe, "/usr/local/bin/ffmpeg")
            except Exception:
                pass
            return exe
    except (ImportError, Exception):
        pass

    # 3. Try auto-installing imageio-ffmpeg
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "imageio-ffmpeg"])
        import importlib
        importlib.invalidate_caches()
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            try:
                if not os.path.exists("/usr/local/bin/ffmpeg"):
                    os.symlink(exe, "/usr/local/bin/ffmpeg")
            except Exception:
                pass
            return exe
    except Exception:
        pass

    return "ffmpeg"


class TranscribeModule(module.Module):
    name = "Transcribe"
    disabled = False

    @command.desc("Transcribe a replied voice/audio message to text.")
    @command.usage("[language code, e.g. de, ru, fr]", optional=True, reply=True)
    async def cmd_transcribe(self, ctx: command.Context) -> None:
        if sr is None:
            await ctx.respond(f"Speech recognition dependency is not installed and auto-installation failed: {globals().get('pip_error', 'Unknown error')}", mode="edit")
            return

        if not ctx.msg.is_reply:
            await ctx.respond("Reply to a voice or audio message to transcribe it.", mode="edit")
            return

        reply_msg = await ctx.msg.get_reply_message()
        if not reply_msg or not (reply_msg.voice or reply_msg.audio or reply_msg.video):
            await ctx.respond("The replied message does not contain any voice, audio, or video media.", mode="edit")
            return

        await ctx.respond("Downloading audio...", mode="edit")

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                media_file = await reply_msg.download_media(file=tmpdir)
            except Exception as e:
                await ctx.respond(f"Failed to download media: {e}", mode="edit")
                return

            if not media_file or not os.path.exists(media_file):
                await ctx.respond("Failed to download media (no file saved).", mode="edit")
                return

            await ctx.respond("Converting audio...", mode="edit")
            wav_file = os.path.join(tmpdir, "output.wav")
            ffmpeg_bin = _get_ffmpeg_binary()

            try:
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg_bin, "-i", media_file, "-ac", "1", "-ar", "16000", wav_file, "-y",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
            except Exception as e:
                await ctx.respond(f"FFmpeg conversion failed: {e}", mode="edit")
                return

            if proc.returncode != 0 or not os.path.exists(wav_file):
                err_msg = stderr.decode(errors="replace").strip() if stderr else f"FFmpeg failed with code {proc.returncode}"
                # Keep error message brief if verbose
                if len(err_msg) > 300:
                    err_msg = err_msg[-300:]
                await ctx.respond(f"FFmpeg conversion failed: {err_msg}", mode="edit")
                return

            await ctx.respond("Transcribing audio...", mode="edit")

            lang = ctx.input.strip() if ctx.input else "en-US"
            if len(lang) == 2:
                if lang.lower() == "en":
                    lang = "en-US"
                else:
                    lang = f"{lang.lower()}-{lang.upper()}"

            loop = asyncio.get_running_loop()
            try:
                text = await loop.run_in_executor(None, self._recognize, wav_file, lang)
                if not text:
                    await ctx.respond("Could not recognize any speech in this message.", mode="edit")
                else:
                    await ctx.respond(f"**Transcription:**\n\n{text}", mode="edit")
            except sr.UnknownValueError:
                await ctx.respond("Speech recognition could not understand the audio.", mode="edit")
            except sr.RequestError as e:
                await ctx.respond(f"Speech recognition service error: {e}", mode="edit")
            except Exception as e:
                await ctx.respond(f"Error during transcription: {e}", mode="edit")

    def _recognize(self, wav_file: str, lang: str) -> str:
        r = sr.Recognizer()
        with sr.AudioFile(wav_file) as source:
            audio = r.record(source)
        return r.recognize_google(audio, language=lang)
