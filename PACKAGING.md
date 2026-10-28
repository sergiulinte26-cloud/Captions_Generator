# Portable Windows test package

## Build

Use 64-bit Python 3.10, 3.11, or 3.12. Run `initial_setup.bat` from this project directory to install the application, CPU alignment libraries, and PyInstaller, then double-click `build_exe.bat`. After pulling this update on another laptop, rerun setup before launching or rebuilding. An existing environment using a different Python version must be recreated with a supported version.

Close any running copy of the packaged executable before building. After a successful build, the script automatically creates and verifies `dist\CaptionsGenerator-Windows-x64.zip`, containing the entire portable folder. It replaces the previous ZIP only after the new archive passes verification. Wait for `Package ready` before sharing; if the build or archiving fails, an older ZIP may still exist.

The build uses `CaptionsGenerator.spec`. The output is `dist\CaptionsGenerator\CaptionsGenerator.exe` plus its `_internal` dependency folder. This test build keeps the console visible for model download status and errors. The source launcher `run_app.bat` is unchanged.

## Share and run

1. Use the automatically generated `dist\CaptionsGenerator-Windows-x64.zip`. Do not send only the EXE.
2. Send the ZIP as a document, or share a download link if your messaging service rejects its size/type.
3. On another Windows x64 laptop, extract the entire ZIP to a writable local folder before launching `CaptionsGenerator.exe`.
4. Leave `_internal` beside the EXE. Python and Visual Studio are not required.
5. Keep the console open while using the application.

The executable is not signed. Windows or antivirus software may warn about it. Only run a package from a trusted source; do not disable security protection to run it.

## First run

Whisper's `small` model weights are NOT included in the package. On a first uncached run, internet access and free disk space are needed to download the model to the user's default Hugging Face cache (normally `%USERPROFILE%\.cache\huggingface`). This happens before the window appears. Later runs reuse the cache. The model runs locally on the CPU using int8.

English captions automatically receive a second, phrase-by-phrase alignment pass using the tested Wav2Vec2 English CPU model. Its weights (roughly 360 MB) download on the first generation to `%LOCALAPPDATA%\CaptionsGenerator\models`, not beside the executable. Subsequent runs reuse that cache; models are not included in the ZIP. Torch libraries increase package size and generation takes longer. Keep the console open for download and phrase progress; the GUI may not respond while processing.

Words remain visible until the next word starts within each inferred phrase. Pauses of at least 200 ms in the initial 30 FPS transcript define phrase groups; first and last boundaries are model estimates, not guaranteed exact speech boundaries. One-frame words such as A are retained in SRT, although CapCut may not display them visibly. Non-English phrases, unsupported characters (including digits), and audio windows longer than 30 seconds retain continuous Whisper timings with a visible timing warning. Download or inference errors are reported rather than silently presented as successful alignment.

Select or drag an MP3 into the window and click Generate. The SRT is saved beside the input MP3, so that directory must be writable. A custom output name should be a simple file name without an extension. Existing output files of the same name may be overwritten.

## Acceptance test on the target laptop

- Launch the extracted EXE on Windows x64 without Python or Visual Studio installed.
- On a first run, allow the model download and verify that the window appears.
- Select a short MP3 with speech and generate an SRT; check words and timestamps.
- Restart and confirm that the cached model loads without another download.
- Test drag-and-drop and Open Output Folder.

A build or a startup test on the development machine alone does not prove clean-laptop compatibility.
