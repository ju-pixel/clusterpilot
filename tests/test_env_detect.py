"""Tests for jobs/env_detect.py — static script analysis, no subprocess."""
from __future__ import annotations

import pytest

from clusterpilot.jobs.env_detect import (
    ScriptEnvironment,
    _julia_third_party,
    _python_third_party,
    analyze_script,
)


# ── Julia import extraction ───────────────────────────────────────────────────

class TestJuliaThirdParty:
    def test_basic_using(self):
        assert _julia_third_party("using CUDA") == ["CUDA"]

    def test_basic_import(self):
        assert _julia_third_party("import Flux") == ["Flux"]

    def test_multi_using(self):
        result = _julia_third_party("using CUDA, Flux, Statistics")
        assert result == ["CUDA", "Flux"]          # Statistics is stdlib

    def test_import_with_colon_syntax(self):
        result = _julia_third_party("import CUDA: CuArray, CuMatrix")
        assert result == ["CUDA"]

    def test_submodule_import_extracts_top_level(self):
        result = _julia_third_party("using Pkg.Artifacts")
        assert result == []                        # Pkg is stdlib

    def test_stdlib_filtered_out(self):
        src = "using LinearAlgebra\nusing Statistics\nusing Random\nusing Printf"
        assert _julia_third_party(src) == []

    def test_pkg_stdlib_filtered(self):
        assert _julia_third_party("using Pkg") == []

    def test_comment_line_ignored(self):
        assert _julia_third_party("# using CUDA") == []

    def test_inline_comment_ignored(self):
        result = _julia_third_party("using CUDA  # GPU arrays")
        assert result == ["CUDA"]

    def test_mixed_stdlib_and_third_party(self):
        src = "using LinearAlgebra, CUDA, Statistics, Flux"
        result = _julia_third_party(src)
        assert result == ["CUDA", "Flux"]

    def test_result_is_sorted(self):
        result = _julia_third_party("using Zygote, CUDA, Flux")
        assert result == sorted(result)

    def test_deduplication(self):
        src = "using CUDA\nusing CUDA"
        assert _julia_third_party(src) == ["CUDA"]

    def test_realistic_script(self):
        src = """\
using LinearAlgebra
using Statistics
using CUDA
using Flux
using Zygote
import Base: show
"""
        result = _julia_third_party(src)
        assert result == ["CUDA", "Flux", "Zygote"]


# ── Python import extraction ──────────────────────────────────────────────────

class TestPythonThirdParty:
    def test_basic_import(self):
        assert _python_third_party("import numpy") == ["numpy"]

    def test_from_import(self):
        assert _python_third_party("from numpy import array") == ["numpy"]

    def test_submodule_from_import(self):
        result = _python_third_party("from sklearn.model_selection import train_test_split")
        assert result == ["sklearn"]

    def test_stdlib_filtered(self):
        src = "import os\nimport sys\nimport re\nimport json\nfrom pathlib import Path"
        assert _python_third_party(src) == []

    def test_relative_import_ignored(self):
        assert _python_third_party("from . import utils") == []

    def test_typing_extensions_excluded(self):
        assert _python_third_party("import typing_extensions") == []

    def test_future_excluded(self):
        assert _python_third_party("from __future__ import annotations") == []

    def test_result_is_sorted(self):
        src = "import torch\nimport numpy\nimport pandas"
        result = _python_third_party(src)
        assert result == sorted(result)

    def test_deduplication(self):
        src = "import numpy\nfrom numpy import array"
        assert _python_third_party(src) == ["numpy"]

    def test_realistic_script(self):
        src = """\
from __future__ import annotations
import os
import sys
from pathlib import Path
import numpy as np
import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader
"""
        result = _python_third_party(src)
        assert result == ["numpy", "sklearn", "torch"]


# ── analyze_script ────────────────────────────────────────────────────────────

class TestAnalyzeScript:
    def test_julia_detected_from_extension(self):
        env = analyze_script("using CUDA", "scripts/run.jl", None)
        assert env.language == "julia"
        assert env.driver_extension == ".jl"

    def test_python_detected_from_extension(self):
        env = analyze_script("import numpy", "train.py", None)
        assert env.language == "python"
        assert env.driver_extension == ".py"

    def test_shell_detected_from_extension(self):
        env = analyze_script("#!/bin/bash\nmodule load julia", "job.sh", None)
        assert env.language == "shell"
        assert env.third_party_imports == []

    def test_julia_detected_from_shebang(self):
        env = analyze_script("#!/usr/bin/env julia\nusing CUDA", None, None)
        assert env.language == "julia"

    def test_python_detected_from_shebang(self):
        env = analyze_script("#!/usr/bin/env python3\nimport numpy", None, None)
        assert env.language == "python"

    def test_manifest_detected_when_present(self):
        env = analyze_script(None, "run.jl", "# Project.toml\n[deps]\nCUDA = \"...\"\n")
        assert env.has_manifest is True

    def test_no_manifest_when_none(self):
        env = analyze_script("using CUDA", "run.jl", None)
        assert env.has_manifest is False

    def test_no_manifest_when_empty_string(self):
        env = analyze_script("using CUDA", "run.jl", "")
        assert env.has_manifest is False

    def test_third_party_imports_extracted_julia(self):
        env = analyze_script("using CUDA, Flux", "run.jl", None)
        assert env.third_party_imports == ["CUDA", "Flux"]

    def test_third_party_imports_extracted_python(self):
        env = analyze_script("import numpy\nimport torch", "train.py", None)
        assert env.third_party_imports == ["numpy", "torch"]

    def test_no_imports_when_no_content(self):
        env = analyze_script(None, "run.jl", None)
        assert env.third_party_imports == []

    def test_shell_has_no_imports(self):
        env = analyze_script("module load julia/1.11.3\njulia run.jl", "job.sh", None)
        assert env.third_party_imports == []

    def test_unknown_extension_no_content(self):
        env = analyze_script("", "script.r", None)
        assert env.language == "unknown"
        assert env.third_party_imports == []


# ── ScriptEnvironment dataclass ───────────────────────────────────────────────

class TestScriptEnvironment:
    def test_fields_accessible(self):
        env = ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["CUDA"],
            driver_extension=".jl",
        )
        assert env.language == "julia"
        assert env.has_manifest is True
        assert env.third_party_imports == ["CUDA"]
        assert env.driver_extension == ".jl"
