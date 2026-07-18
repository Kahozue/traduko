"""Dubbing engine integration (diarization + TTS synthesis).

The heavy engine packages (voxcpm, pyannote.audio, torch) live in a
separate managed venv under the data root; core talks to them through a
JSON-lines subprocess running runner.py inside that venv.
"""
