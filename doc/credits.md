# License and credits

[Back to the README](../README.md)

SubSync Echo is free software under the [GNU General Public License v3](../LICENSE).

- Based on [SubSync](https://github.com/sc0ty/subsync) by Michał Szymaniak, GPL-3.0.
- Speech recognition: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [CTranslate2](https://github.com/OpenNMT/CTranslate2) (MIT), with OpenAI's [Whisper](https://github.com/openai/whisper) `small` model (MIT), downloaded from [Hugging Face](https://huggingface.co/Systran/faster-whisper-small).
- Speech detection: [Silero VAD](https://github.com/snakers4/silero-vad) (MIT), through [ONNX Runtime](https://github.com/microsoft/onnxruntime) (MIT).
- Speech recognition for other languages: [CMU Sphinx](https://github.com/cmusphinx) (BSD).
- Translation: Meta's [M2M100](https://huggingface.co/facebook/m2m100_418M) 418M model (MIT), in the [CTranslate2 conversion by jncraton](https://huggingface.co/jncraton/m2m100_418M-ct2-int8) (MIT), with [SentencePiece](https://github.com/google/sentencepiece) (Apache-2.0).
- Audio and video: [FFmpeg](https://ffmpeg.org) 5.1.2, the [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) full shared build (GPL-3.0); source code at [ffmpeg.org/releases/ffmpeg-5.1.2.tar.xz](https://ffmpeg.org/releases/ffmpeg-5.1.2.tar.xz). Also [PyAV](https://github.com/PyAV-Org/PyAV) (BSD).
- Test films: [Tears of Steel](https://mango.blender.org) by the Blender Foundation (CC-BY 3.0), shown in the README's clip and used in the end-to-end test, [Sita Sings the Blues](https://sitasingstheblues.com) by Nina Paley (public domain, CC0), with community subtitles from [Amara](https://amara.org/en/videos/YkwgVDEZTA0g/info/) and [archive.org](https://archive.org/details/SitaSingsTheBluesCsSubtitles), and [Sintel](https://durian.blender.org) by the Blender Foundation (CC-BY 3.0); the tests download them, they aren't included.
- Window: [wxPython](https://wxpython.org) (wxWindows Library Licence). Subtitles: [pysubs2](https://github.com/tkarabela/pysubs2) (MIT). Engine bindings: [pybind11](https://github.com/pybind/pybind11) (BSD).
