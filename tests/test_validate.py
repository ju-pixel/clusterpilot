"""Tests for jobs/validate.py: deterministic pre-submit checks on a script.

Only the ``bash -n`` check is allowed to run a real subprocess, and only in the
few tests that exercise it deliberately. Everything else either calls a check
function directly or has bash monkeypatched away.
"""
from __future__ import annotations

import dataclasses
import subprocess

import pytest

from clusterpilot.cluster.probe import PartitionInfo
from clusterpilot.jobs import validate
from clusterpilot.jobs.validate import (
    Finding,
    IntentError,
    Severity,
    SubmitIntent,
    blocking,
    format_findings,
    validate_script,
)

# A script with nothing wrong with it: shebang, correctly cased directives, a
# module load, and a driver invocation, ending in a newline.
CLEAN_SCRIPT = """#!/bin/bash
#SBATCH --job-name=demo
#SBATCH --account=def-stamps
#SBATCH --partition=stamps
#SBATCH --time=02:00:00
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --array=0-9
#SBATCH --output=%x-%A-%a.out

module load julia/1.11.3

julia --project=. scripts/run.jl
"""


@pytest.fixture
def clean_intent():
    return SubmitIntent(
        array_spec="0-9",
        param_row_count=10,
        driver_rel="scripts/run.jl",
        upload_paths=("Project.toml", "Manifest.toml", "src/***", "scripts/run.jl"),
        partition_name="stamps",
        requested_walltime="02:00:00",
    )


@pytest.fixture
def partitions():
    return [
        PartitionInfo("skylake", "7-00:00:00", "", 10, is_default=True),
        PartitionInfo("stamps", "21-00:00:00", "gpu:v100:4", 3, is_default=False),
        PartitionInfo("short", "03:00:00", "gpu:l40s:2", 2, is_default=False),
        PartitionInfo("endless", "infinite", "", 1, is_default=False),
    ]


@pytest.fixture
def no_bash(monkeypatch):
    """Remove bash so validate_script never shells out in a unit test."""
    monkeypatch.setattr(validate.shutil, "which", lambda name: None)


def _sbatch(*directives: str, body: str = "julia --project=. scripts/run.jl") -> str:
    """Build a small script from #SBATCH directive bodies."""
    lines = ["#!/bin/bash"] + [f"#SBATCH {d}" for d in directives] + ["", body, ""]
    return "\n".join(lines)


# ── validate_script, end to end ───────────────────────────────────────────────

class TestValidateScript:
    def test_clean_script_has_no_findings(self, clean_intent, partitions):
        assert validate_script(CLEAN_SCRIPT, intent=clean_intent, partitions=partitions) == []

    def test_clean_script_without_probe_data_has_no_findings(self, clean_intent):
        assert validate_script(CLEAN_SCRIPT, intent=clean_intent) == []

    def test_empty_intent_on_clean_script_has_no_findings(self):
        assert validate_script(CLEAN_SCRIPT, intent=SubmitIntent()) == []

    def test_broken_script_yields_findings_not_exceptions(self, partitions, no_bash):
        script = (
            "#SBATCH --job-name=demo\n"
            "#sbatch --gres=gpu:4\n"
            "#SBATCH --time=30-00:00:00\n"
            "#SBATCH --partition=stamps\n"
            "\n"
            "julia --project=. scripts/run.jl\n"
        )
        intent = SubmitIntent(
            array_spec="0-4",
            driver_rel="scripts/run.jl",
            upload_paths=("Project.toml",),
            partition_name="stamps",
        )
        findings = validate_script(script, intent=intent, partitions=partitions)
        slugs = {f.check for f in findings}
        assert slugs == {
            "shebang",
            "miscased-directive",
            "array-missing",
            "walltime-over-partition",
            "driver-not-uploaded",
        }
        assert blocking(findings) is True

    def test_findings_are_frozen(self, no_bash):
        findings = validate_script("echo hello\n", intent=SubmitIntent())
        assert findings[0].check == "shebang"
        with pytest.raises(dataclasses.FrozenInstanceError):
            findings[0].message = "changed"


# ── SubmitIntent validation ───────────────────────────────────────────────────

class TestIntentValidation:
    def test_none_row_count_is_allowed(self, no_bash):
        assert validate_script(CLEAN_SCRIPT, intent=SubmitIntent(param_row_count=None)) == []

    def test_zero_row_count_raises(self, no_bash):
        with pytest.raises(IntentError, match="at least 1"):
            validate_script(CLEAN_SCRIPT, intent=SubmitIntent(param_row_count=0))

    def test_negative_row_count_raises(self, no_bash):
        with pytest.raises(IntentError, match="at least 1"):
            validate_script(CLEAN_SCRIPT, intent=SubmitIntent(param_row_count=-3))

    def test_non_integer_row_count_raises(self, no_bash):
        with pytest.raises(IntentError, match="must be an int"):
            validate_script(CLEAN_SCRIPT, intent=SubmitIntent(param_row_count="10"))

    def test_boolean_row_count_raises(self, no_bash):
        with pytest.raises(IntentError, match="must be an int"):
            validate_script(CLEAN_SCRIPT, intent=SubmitIntent(param_row_count=True))

    def test_wrong_intent_type_raises(self, no_bash):
        with pytest.raises(IntentError, match="must be a SubmitIntent"):
            validate_script(CLEAN_SCRIPT, intent={"array_spec": "0-9"})

    def test_intent_error_is_a_value_error(self):
        assert issubclass(IntentError, ValueError)


# ── shebang ───────────────────────────────────────────────────────────────────

class TestShebang:
    def test_present_gives_no_finding(self):
        assert validate._check_shebang("#!/bin/bash\necho hi\n") == []

    def test_absent_blocks(self):
        findings = validate._check_shebang("#SBATCH --time=01:00:00\necho hi\n")
        assert len(findings) == 1
        assert findings[0].check == "shebang"
        assert findings[0].severity is Severity.BLOCKING
        assert findings[0].line == 1

    def test_shebang_below_the_first_line_blocks(self):
        findings = validate._check_shebang("\n#!/bin/bash\necho hi\n")
        assert findings[0].check == "shebang"

    def test_empty_script_blocks(self):
        assert validate._check_shebang("")[0].check == "shebang"


# ── bash -n ───────────────────────────────────────────────────────────────────

class TestBashSyntax:
    def test_valid_script_passes(self):
        # Genuinely runs bash -n, the one subprocess these tests are allowed.
        assert validate._check_bash_syntax(CLEAN_SCRIPT) == []

    def test_malformed_script_blocks(self):
        broken = '#!/bin/bash\nfor i in 1 2 3; do\n  echo "unterminated\n'
        findings = validate._check_bash_syntax(broken)
        assert len(findings) == 1
        assert findings[0].check == "bash-syntax"
        assert findings[0].severity is Severity.BLOCKING
        # The temporary file path never leaks into the message.
        assert "clusterpilot_validate_" not in findings[0].message

    def test_skipped_when_bash_is_absent(self, monkeypatch):
        monkeypatch.setattr(validate.shutil, "which", lambda name: None)

        def fail(*args, **kwargs):
            raise AssertionError("subprocess must not run when bash is absent")

        monkeypatch.setattr(validate.subprocess, "run", fail)
        broken = '#!/bin/bash\necho "unterminated\n'
        assert validate._check_bash_syntax(broken) == []

    def test_timeout_is_skipped(self, monkeypatch):
        monkeypatch.setattr(validate.shutil, "which", lambda name: "/bin/bash")

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["bash", "-n"], timeout=1.0)

        monkeypatch.setattr(validate.subprocess, "run", timeout)
        assert validate._check_bash_syntax("#!/bin/bash\n") == []

    def test_os_error_is_skipped(self, monkeypatch):
        monkeypatch.setattr(validate.shutil, "which", lambda name: "/bin/bash")

        def boom(*args, **kwargs):
            raise OSError("no such executable")

        monkeypatch.setattr(validate.subprocess, "run", boom)
        assert validate._check_bash_syntax("#!/bin/bash\n") == []

    def test_line_number_recovered_from_stderr(self, monkeypatch):
        monkeypatch.setattr(validate.shutil, "which", lambda name: "/bin/bash")

        def failed(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args[0]),
                returncode=2,
                stdout="",
                stderr="script.sh: line 12: syntax error near unexpected token `fi'\n",
            )

        monkeypatch.setattr(validate.subprocess, "run", failed)
        findings = validate._check_bash_syntax("#!/bin/bash\n")
        assert findings[0].line == 12
        assert "syntax error" in findings[0].message

    def test_silent_failure_still_reports(self, monkeypatch):
        monkeypatch.setattr(validate.shutil, "which", lambda name: "/bin/bash")

        def failed(*args, **kwargs):
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        monkeypatch.setattr(validate.subprocess, "run", failed)
        findings = validate._check_bash_syntax("#!/bin/bash\n")
        assert len(findings) == 1
        assert findings[0].line is None


# ── mis-cased directives ──────────────────────────────────────────────────────

class TestMiscasedDirective:
    def test_correct_case_gives_no_finding(self):
        assert validate._check_miscased_directives(CLEAN_SCRIPT) == []

    def test_lowercase_directive_blocks(self):
        script = "#!/bin/bash\n#SBATCH --time=01:00:00\n#sbatch --gres=gpu:1\n"
        findings = validate._check_miscased_directives(script)
        assert len(findings) == 1
        assert findings[0].check == "miscased-directive"
        assert findings[0].severity is Severity.BLOCKING
        assert findings[0].line == 3
        assert "#sbatch --gres=gpu:1" in findings[0].message

    def test_mixed_case_directive_blocks(self):
        findings = validate._check_miscased_directives("#!/bin/bash\n#Sbatch --mem=16G\n")
        assert findings[0].line == 2

    def test_every_offending_line_is_reported(self):
        script = (
            "#!/bin/bash\n#sbatch --mem=16G\n#SBATCH --time=01:00:00\n"
            "#SBATCH --gres=gpu:1\n#sBaTcH --nodes=1\n"
        )
        findings = validate._check_miscased_directives(script)
        assert [f.line for f in findings] == [2, 5]

    def test_ordinary_comment_is_ignored(self):
        script = "#!/bin/bash\n# sbatch is what we run later\n#SBATCH --time=01:00:00\n"
        assert validate._check_miscased_directives(script) == []

    def test_word_that_merely_starts_with_sbatch_is_ignored(self):
        assert validate._check_miscased_directives("#!/bin/bash\n#sbatchery --mem=1G\n") == []


# ── job array ─────────────────────────────────────────────────────────────────

class TestArrayTaskCounting:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("0-9", 10),
            ("1-100", 100),
            ("1-100%5", 100),
            ("0-8:2", 5),
            ("0-9:3%2", 4),
            ("7", 1),
            ("1,3,5", 3),
            ("0-3,10-11", 6),
        ],
    )
    def test_counts(self, spec, expected):
        assert validate._count_array_tasks(spec) == expected

    @pytest.mark.parametrize("spec", ["", "abc", "9-0", "0-", "0-9:0", "0-9:x", "%5", "1,,3"])
    def test_unparseable_returns_none(self, spec):
        assert validate._count_array_tasks(spec) is None


class TestArrayCheck:
    def test_no_table_and_no_spec_gives_no_finding(self):
        script = _sbatch("--time=01:00:00")
        assert validate._check_array(script, SubmitIntent()) == []

    def test_row_count_matching_emitted_array_is_clean(self):
        script = _sbatch("--array=0-9")
        assert validate._check_array(script, SubmitIntent(param_row_count=10)) == []

    def test_row_count_mismatch_blocks(self):
        script = _sbatch("--array=0-9")
        findings = validate._check_array(script, SubmitIntent(param_row_count=40))
        assert len(findings) == 1
        assert findings[0].check == "array-mismatch"
        assert findings[0].severity is Severity.BLOCKING
        assert "40 rows" in findings[0].message

    def test_step_and_concurrency_limit_are_counted(self):
        script = _sbatch("--array=0-8:2%2")
        assert validate._check_array(script, SubmitIntent(param_row_count=5)) == []

    def test_comma_list_is_counted(self):
        script = _sbatch("--array=1,3,5")
        assert validate._check_array(script, SubmitIntent(param_row_count=3)) == []

    def test_table_with_no_emitted_array_blocks(self):
        script = _sbatch("--time=01:00:00")
        findings = validate._check_array(script, SubmitIntent(param_row_count=4))
        assert findings[0].check == "array-mismatch"
        assert findings[0].line is None

    def test_unparseable_emitted_spec_blocks(self):
        script = _sbatch("--array=nonsense")
        findings = validate._check_array(script, SubmitIntent(param_row_count=4))
        assert findings[0].check == "array-mismatch"
        assert "could not be read" in findings[0].message

    def test_explicit_spec_matching_emitted_is_clean(self):
        script = _sbatch("--array=1-100%5")
        assert validate._check_array(script, SubmitIntent(array_spec="1-100%5")) == []

    def test_explicit_spec_mismatch_blocks(self):
        script = _sbatch("--array=0-9")
        findings = validate._check_array(script, SubmitIntent(array_spec="0-4"))
        assert findings[0].check == "array-mismatch"
        assert "0-4" in findings[0].message

    def test_explicit_spec_wins_over_the_row_count(self):
        # An explicit subset of a longer table stays possible.
        script = _sbatch("--array=0-9")
        intent = SubmitIntent(array_spec="0-9", param_row_count=40)
        assert validate._check_array(script, intent) == []

    def test_missing_array_with_explicit_spec_blocks(self):
        script = _sbatch("--time=01:00:00")
        findings = validate._check_array(script, SubmitIntent(array_spec="0-9"))
        assert len(findings) == 1
        assert findings[0].check == "array-missing"
        assert findings[0].severity is Severity.BLOCKING

    def test_miscased_array_directive_counts_as_missing(self):
        script = "#!/bin/bash\n#sbatch --array=0-9\n\necho hi\n"
        findings = validate._check_array(script, SubmitIntent(array_spec="0-9"))
        assert findings[0].check == "array-missing"

    def test_space_separated_directive_is_read(self):
        script = _sbatch("--array 0-9")
        assert validate._check_array(script, SubmitIntent(param_row_count=10)) == []

    def test_last_directive_wins(self):
        script = _sbatch("--array=0-9", "--array=0-3")
        assert validate._check_array(script, SubmitIntent(param_row_count=4)) == []


# ── GPU count ─────────────────────────────────────────────────────────────────

class TestGpuCount:
    def test_single_gpu_gres_gives_no_finding(self):
        assert validate._check_gpu_count(_sbatch("--gres=gpu:1")) == []

    def test_single_gpu_gpus_form_gives_no_finding(self):
        assert validate._check_gpu_count(_sbatch("--gpus=a100:1")) == []

    def test_typeless_gres_without_a_count_gives_no_finding(self):
        assert validate._check_gpu_count(_sbatch("--gres=gpu")) == []

    def test_multi_gpu_gres_warns(self):
        findings = validate._check_gpu_count(_sbatch("--gres=gpu:4"))
        assert len(findings) == 1
        assert findings[0].check == "gpu-count"
        assert findings[0].severity is Severity.WARNING

    def test_typed_multi_gpu_gres_warns(self):
        findings = validate._check_gpu_count(_sbatch("--gres=gpu:a100:4"))
        assert findings[0].check == "gpu-count"
        assert "4 GPUs" in findings[0].message

    def test_multi_gpu_gpus_form_warns(self):
        findings = validate._check_gpu_count(_sbatch("--gpus=2"))
        assert findings[0].check == "gpu-count"

    def test_a_multi_task_job_is_not_warned_about(self):
        script = _sbatch("--gres=gpu:4", "--ntasks=4")
        assert validate._check_gpu_count(script) == []

    def test_a_multi_node_job_is_not_warned_about(self):
        script = _sbatch("--gres=gpu:4", "--nodes=2")
        assert validate._check_gpu_count(script) == []

    def test_short_form_task_count_is_respected(self):
        script = _sbatch("--gres=gpu:4", "-n 4")
        assert validate._check_gpu_count(script) == []

    def test_an_array_job_is_still_single_task(self):
        script = _sbatch("--gres=gpu:4", "--array=0-9", "--ntasks=1")
        assert validate._check_gpu_count(script)[0].check == "gpu-count"

    def test_gpu_count_never_blocks(self):
        findings = validate._check_gpu_count(_sbatch("--gres=gpu:8"))
        assert blocking(findings) is False

    def test_a_duplicated_request_reports_each_line(self):
        script = _sbatch("--gpus=a100:4", "--gres=gpu:a100:4")
        assert [f.line for f in validate._check_gpu_count(script)] == [2, 3]


# ── GPU size ──────────────────────────────────────────────────────────────────

class TestGpuSize:
    """The GPU SIZE picked on F2 must survive into the emitted request.

    A MIG slice and a whole card are different resources to SLURM: asking for
    the wrong one gets the job hardware the user did not choose, so this check
    blocks rather than warns.
    """

    def test_matching_slice_gives_no_finding(self):
        script = _sbatch("--gres=gpu:a100_3g.20gb:1")
        intent = SubmitIntent(gpu_size="a100_3g.20gb")
        assert validate._check_gpu_size(script, intent) == []

    def test_matching_whole_card_gives_no_finding(self):
        script = _sbatch("--gres=gpu:a100:1")
        assert validate._check_gpu_size(script, SubmitIntent(gpu_size="a100")) == []

    def test_whole_card_where_a_slice_was_picked_blocks(self):
        script = _sbatch("--gres=gpu:a100:1")
        findings = validate._check_gpu_size(script, SubmitIntent(gpu_size="a100_3g.20gb"))
        assert len(findings) == 1
        assert findings[0].check == "gpu-size"
        assert findings[0].severity is Severity.BLOCKING
        assert "a100_3g.20gb" in findings[0].message
        assert findings[0].line == 2

    def test_typeless_request_blocks(self):
        script = _sbatch("--gres=gpu:1")
        findings = validate._check_gpu_size(script, SubmitIntent(gpu_size="a100"))
        assert findings[0].check == "gpu-size"
        assert "no GPU type" in findings[0].message

    def test_gpus_form_is_checked_too(self):
        script = _sbatch("--gpus=a100:1")
        assert validate._check_gpu_size(script, SubmitIntent(gpu_size="a100")) == []
        findings = validate._check_gpu_size(script, SubmitIntent(gpu_size="v100"))
        assert findings[0].check == "gpu-size"

    def test_no_picked_size_skips_the_check(self):
        script = _sbatch("--gres=gpu:1")
        assert validate._check_gpu_size(script, SubmitIntent()) == []

    def test_a_cpu_script_has_nothing_to_check(self):
        script = _sbatch("--time=01:00:00")
        assert validate._check_gpu_size(script, SubmitIntent(gpu_size="a100")) == []

    def test_the_check_runs_end_to_end(self, partitions):
        script = _sbatch("--partition=stamps", "--time=01:00:00", "--gres=gpu:a100:1")
        findings = validate_script(
            script,
            intent=SubmitIntent(partition_name="stamps", gpu_size="a100_3g.20gb"),
            partitions=partitions,
        )
        assert [f.check for f in findings] == ["gpu-size"]
        assert blocking(findings) is True


# ── walltime against the probed partition limit ───────────────────────────────

class TestWalltimeParsing:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [
            ("60", 3600),
            ("05:30", 330),
            ("02:30:00", 9000),
            ("1-00", 86400),
            ("1-12:00", 129600),
            ("7-00:00:00", 604800),
        ],
    )
    def test_parses(self, text, seconds):
        assert validate._parse_walltime_seconds(text) == seconds

    @pytest.mark.parametrize("text", ["", "infinite", "UNLIMITED", "n/a", "1:2:3:4", "abc", "-1"])
    def test_unparseable_returns_none(self, text):
        assert validate._parse_walltime_seconds(text) is None


class TestWalltimeCheck:
    def test_within_the_limit_is_clean(self, partitions):
        script = _sbatch("--time=02:00:00")
        intent = SubmitIntent(partition_name="short")
        assert validate._check_walltime(script, intent, partitions) == []

    def test_over_the_limit_blocks(self, partitions):
        script = _sbatch("--time=12:00:00")
        intent = SubmitIntent(partition_name="short")
        findings = validate._check_walltime(script, intent, partitions)
        assert len(findings) == 1
        assert findings[0].check == "walltime-over-partition"
        assert findings[0].severity is Severity.BLOCKING
        assert "03:00:00" in findings[0].message
        assert findings[0].line == 2

    def test_day_form_over_the_limit_blocks(self, partitions):
        script = _sbatch("--time=30-00:00:00")
        intent = SubmitIntent(partition_name="stamps")
        assert validate._check_walltime(script, intent, partitions)[0].check == (
            "walltime-over-partition"
        )

    def test_exactly_the_limit_is_clean(self, partitions):
        script = _sbatch("--time=03:00:00")
        intent = SubmitIntent(partition_name="short")
        assert validate._check_walltime(script, intent, partitions) == []

    def test_skipped_without_probe_data(self):
        script = _sbatch("--time=30-00:00:00")
        assert validate._check_walltime(script, SubmitIntent(partition_name="short"), None) == []
        assert validate._check_walltime(script, SubmitIntent(partition_name="short"), []) == []

    def test_skipped_when_no_partition_was_chosen(self, partitions):
        script = _sbatch("--time=30-00:00:00")
        assert validate._check_walltime(script, SubmitIntent(), partitions) == []

    def test_skipped_when_the_partition_is_not_in_the_probe(self, partitions):
        script = _sbatch("--time=30-00:00:00")
        intent = SubmitIntent(partition_name="not-probed")
        assert validate._check_walltime(script, intent, partitions) == []

    def test_skipped_when_the_limit_is_unbounded(self, partitions):
        script = _sbatch("--time=30-00:00:00")
        intent = SubmitIntent(partition_name="endless")
        assert validate._check_walltime(script, intent, partitions) == []

    def test_skipped_when_no_time_is_emitted(self, partitions):
        script = _sbatch("--gres=gpu:1")
        intent = SubmitIntent(partition_name="short", requested_walltime="30-00:00:00")
        assert validate._check_walltime(script, intent, partitions) == []

    def test_skipped_when_the_emitted_time_is_unreadable(self, partitions):
        script = _sbatch("--time=soon")
        intent = SubmitIntent(partition_name="short")
        assert validate._check_walltime(script, intent, partitions) == []


# ── driver in the upload set ──────────────────────────────────────────────────

class TestDriverUploaded:
    def test_uploaded_driver_is_clean(self):
        intent = SubmitIntent(
            driver_rel="scripts/run.jl",
            upload_paths=("Project.toml", "scripts/run.jl"),
        )
        assert validate._check_driver_uploaded(CLEAN_SCRIPT, intent) == []

    def test_missing_driver_blocks(self):
        intent = SubmitIntent(
            driver_rel="scripts/run.jl",
            upload_paths=("Project.toml", "Manifest.toml"),
        )
        findings = validate._check_driver_uploaded(CLEAN_SCRIPT, intent)
        assert len(findings) == 1
        assert findings[0].check == "driver-not-uploaded"
        assert findings[0].severity is Severity.BLOCKING
        assert findings[0].line == 14

    def test_directory_include_covers_the_driver(self):
        intent = SubmitIntent(
            driver_rel="src/drivers/run.jl",
            upload_paths=("Project.toml", "src/***"),
        )
        script = "#!/bin/bash\njulia --project=. src/drivers/run.jl\n"
        assert validate._check_driver_uploaded(script, intent) == []

    def test_bare_directory_entry_covers_the_driver(self):
        intent = SubmitIntent(driver_rel="scripts/run.jl", upload_paths=("scripts",))
        assert validate._check_driver_uploaded(CLEAN_SCRIPT, intent) == []

    def test_empty_upload_set_is_skipped(self):
        intent = SubmitIntent(driver_rel="scripts/run.jl", upload_paths=())
        assert validate._check_driver_uploaded(CLEAN_SCRIPT, intent) == []

    def test_no_driver_named_is_skipped(self):
        intent = SubmitIntent(driver_rel="", upload_paths=("Project.toml",))
        assert validate._check_driver_uploaded(CLEAN_SCRIPT, intent) == []

    def test_driver_never_invoked_is_skipped(self):
        intent = SubmitIntent(
            driver_rel="scripts/other.jl",
            upload_paths=("Project.toml",),
        )
        assert validate._check_driver_uploaded(CLEAN_SCRIPT, intent) == []

    def test_a_longer_path_is_not_taken_as_the_invocation(self):
        script = "#!/bin/bash\njulia --project=. vendor/scripts/run.jl\n"
        intent = SubmitIntent(driver_rel="scripts/run.jl", upload_paths=("Project.toml",))
        assert validate._check_driver_uploaded(script, intent) == []

    def test_dot_slash_invocation_is_recognised(self):
        script = "#!/bin/bash\n./scripts/run.sh\n"
        intent = SubmitIntent(driver_rel="scripts/run.sh", upload_paths=("Project.toml",))
        assert validate._check_driver_uploaded(script, intent)[0].line == 2

    def test_a_mention_in_a_comment_is_not_an_invocation(self):
        script = "#!/bin/bash\n# scripts/run.jl is the driver\necho hi\n"
        intent = SubmitIntent(driver_rel="scripts/run.jl", upload_paths=("Project.toml",))
        assert validate._check_driver_uploaded(script, intent) == []

    def test_a_quoted_invocation_is_recognised(self):
        script = '#!/bin/bash\njulia --project=. "scripts/run.jl"\n'
        intent = SubmitIntent(driver_rel="scripts/run.jl", upload_paths=("Project.toml",))
        assert validate._check_driver_uploaded(script, intent)[0].check == "driver-not-uploaded"


# ── stdbuf and LD_PRELOAD ─────────────────────────────────────────────────────

class TestStdbuf:
    def test_clean_script_gives_no_finding(self):
        assert validate._check_stdbuf(CLEAN_SCRIPT) == []

    def test_wrapped_driver_blocks(self):
        script = (
            "#!/bin/bash\n"
            "module load julia/1.11.3\n"
            "stdbuf -oL -eL julia --project=. run.jl\n"
        )
        findings = validate._check_stdbuf(script)
        assert len(findings) == 1
        assert findings[0].check == "stdbuf"
        assert findings[0].severity is Severity.BLOCKING
        assert findings[0].line == 3
        assert "GLIBC_ABI_DT_RELR not found" in findings[0].message
        assert "python -u" in findings[0].message

    def test_ld_preload_blocks(self):
        script = "#!/bin/bash\nexport LD_PRELOAD=/x.so\njulia --project=. run.jl\n"
        findings = validate._check_stdbuf(script)
        assert len(findings) == 1
        assert findings[0].check == "stdbuf"
        assert findings[0].line == 2

    def test_one_finding_per_offending_line(self):
        script = "#!/bin/bash\nLD_PRELOAD=/x.so stdbuf -oL python -u run.py\n"
        assert len(validate._check_stdbuf(script)) == 1

    def test_a_mention_in_a_comment_is_ignored(self):
        script = (
            "#!/bin/bash\n"
            "# do not use stdbuf here, and never set LD_PRELOAD=/x.so\n"
            "julia --project=. run.jl   # stdbuf would break ptxas\n"
        )
        assert validate._check_stdbuf(script) == []

    def test_a_word_ending_in_stdbuf_is_not_a_command(self):
        script = "#!/bin/bash\n./my-stdbuf-wrapper.sh run.jl\ncp libstdbuf.so out/\n"
        assert validate._check_stdbuf(script) == []

    def test_surfaces_through_validate_script(self, no_bash):
        script = "#!/bin/bash\nstdbuf -oL julia --project=. run.jl\n"
        findings = validate_script(script, intent=SubmitIntent())
        assert [f.check for f in findings] == ["stdbuf"]
        assert blocking(findings) is True


# ── truncation ────────────────────────────────────────────────────────────────

class TestTruncated:
    def test_complete_script_gives_no_finding(self):
        assert validate._check_truncated(CLEAN_SCRIPT) == []

    def test_a_missing_final_newline_alone_gives_no_finding(self):
        assert validate._check_truncated(CLEAN_SCRIPT.rstrip("\n")) == []

    def test_unterminated_quote_warns(self):
        findings = validate._check_truncated('#!/bin/bash\necho "half a line')
        assert len(findings) == 1
        assert findings[0].check == "truncated"
        assert findings[0].severity is Severity.WARNING
        assert findings[0].line == 2

    def test_trailing_continuation_warns(self):
        findings = validate._check_truncated("#!/bin/bash\njulia --project=. \\")
        assert findings[0].check == "truncated"

    def test_trailing_pipe_warns(self):
        assert validate._check_truncated("#!/bin/bash\nsort results.txt |")[0].check == "truncated"

    def test_dangling_directive_warns(self):
        assert validate._check_truncated("#!/bin/bash\n#SBATCH --time=")[0].check == "truncated"

    def test_a_closed_quote_is_not_flagged(self):
        assert validate._check_truncated('#!/bin/bash\necho "all here"') == []

    def test_an_escaped_quote_is_not_flagged(self):
        assert validate._check_truncated('#!/bin/bash\necho "a \\" b"') == []

    def test_a_quote_inside_a_comment_is_not_flagged(self):
        assert validate._check_truncated("#!/bin/bash\n# it's fine\necho hi") == []

    def test_truncation_never_blocks(self):
        assert blocking(validate._check_truncated('#!/bin/bash\necho "cut')) is False

    def test_empty_script_gives_no_finding(self):
        assert validate._check_truncated("") == []


# ── blocking ──────────────────────────────────────────────────────────────────

class TestBlocking:
    def test_empty_is_not_blocking(self):
        assert blocking([]) is False

    def test_warnings_alone_are_not_blocking(self):
        findings = [Finding("gpu-count", Severity.WARNING, "four GPUs")]
        assert blocking(findings) is False

    def test_one_blocking_finding_blocks(self):
        findings = [
            Finding("gpu-count", Severity.WARNING, "four GPUs"),
            Finding("shebang", Severity.BLOCKING, "no shebang"),
        ]
        assert blocking(findings) is True


# ── format_findings ───────────────────────────────────────────────────────────

class TestFormatFindings:
    def test_empty_renders_as_an_empty_string(self):
        assert format_findings([]) == ""

    def test_blocking_findings_come_first(self):
        findings = [
            Finding("gpu-count", Severity.WARNING, "four GPUs"),
            Finding("shebang", Severity.BLOCKING, "no shebang", line=1),
        ]
        lines = format_findings(findings).splitlines()
        assert lines[0].startswith("BLOCKING")
        assert lines[1].startswith("WARNING")

    def test_equal_severity_keeps_its_order(self):
        findings = [
            Finding("shebang", Severity.BLOCKING, "first"),
            Finding("array-missing", Severity.BLOCKING, "second"),
        ]
        lines = format_findings(findings).splitlines()
        assert "first" in lines[0]
        assert "second" in lines[1]

    def test_one_line_per_finding(self):
        findings = [Finding("truncated", Severity.WARNING, "a\nmultiline\nmessage")]
        rendered = format_findings(findings)
        assert rendered.count("\n") == 0
        assert "a multiline message" in rendered

    def test_line_number_is_shown_when_known(self):
        findings = [Finding("miscased-directive", Severity.BLOCKING, "oops", line=7)]
        assert "(line 7)" in format_findings(findings)

    def test_line_number_is_omitted_when_unknown(self):
        findings = [Finding("array-missing", Severity.BLOCKING, "oops")]
        assert "(line" not in format_findings(findings)

    def test_the_check_slug_is_shown(self):
        findings = [Finding("walltime-over-partition", Severity.BLOCKING, "oops")]
        assert "walltime-over-partition" in format_findings(findings)


# ── Check: account walltime ceiling (issue #23) ───────────────────────────────

class TestAccountWalltimeCheck:
    _WALL = {"def-stamps": "1-00:00:00", "def-stamps_gpu": ""}

    def test_over_the_account_ceiling_blocks(self):
        script = _sbatch("--time=3-00:00:00")
        intent = SubmitIntent(account="def-stamps")
        findings = validate._check_account_walltime(script, intent, self._WALL)
        assert len(findings) == 1
        assert findings[0].check == "account-walltime"
        assert findings[0].severity is Severity.BLOCKING
        assert "def-stamps" in findings[0].message
        assert "1-00:00:00" in findings[0].message
        assert findings[0].line == 2

    def test_within_the_ceiling_is_clean(self):
        script = _sbatch("--time=12:00:00")
        intent = SubmitIntent(account="def-stamps")
        assert validate._check_account_walltime(script, intent, self._WALL) == []

    def test_exactly_the_ceiling_is_clean(self):
        script = _sbatch("--time=1-00:00:00")
        intent = SubmitIntent(account="def-stamps")
        assert validate._check_account_walltime(script, intent, self._WALL) == []

    def test_an_empty_ceiling_is_a_no_op(self):
        # sacctmgr reports "" for an account with no limit set.
        script = _sbatch("--time=30-00:00:00")
        intent = SubmitIntent(account="def-stamps_gpu")
        assert validate._check_account_walltime(script, intent, self._WALL) == []

    def test_an_unprobed_account_is_a_no_op(self):
        script = _sbatch("--time=30-00:00:00")
        intent = SubmitIntent(account="def-someone-else")
        assert validate._check_account_walltime(script, intent, self._WALL) == []

    def test_skipped_without_probe_data(self):
        # sacctmgr fails outright from a DRAC login node; absent stays silent.
        script = _sbatch("--time=30-00:00:00")
        intent = SubmitIntent(account="def-stamps")
        assert validate._check_account_walltime(script, intent, None) == []
        assert validate._check_account_walltime(script, intent, {}) == []

    def test_skipped_when_no_account_is_configured(self):
        script = _sbatch("--time=30-00:00:00")
        assert validate._check_account_walltime(script, SubmitIntent(), self._WALL) == []

    def test_reached_through_validate_script(self, no_bash):
        script = _sbatch("--time=3-00:00:00")
        findings = validate_script(
            script,
            intent=SubmitIntent(account="def-stamps"),
            account_max_wall=self._WALL,
        )
        assert any(f.check == "account-walltime" for f in findings)


# ── Check: cores and memory per node (issue #22) ──────────────────────────────

@pytest.fixture
def sized_partitions():
    return [
        PartitionInfo("stamps", "21-00:00:00", "gpu:v100:4", 3,
                      is_default=False, cpus=32, memory_mb=192000),
        PartitionInfo("unsized", "7-00:00:00", "", 4, is_default=False),
    ]


class TestMemoryParsing:
    @pytest.mark.parametrize("text,expected", [
        ("4000", 4000 * 1024),      # bare value means MB
        ("4000M", 4000 * 1024),
        ("16G", 16 * 1024 ** 2),
        ("1T", 1024 ** 3),
        ("512K", 512),
        ("16GB", 16 * 1024 ** 2),
    ])
    def test_units(self, text, expected):
        assert validate._parse_memory_kb(text) == expected

    @pytest.mark.parametrize("text", ["", "   ", "lots", "16X", "1.5G"])
    def test_unreadable_values_are_none(self, text):
        assert validate._parse_memory_kb(text) is None


class TestResourcesCheck:
    def test_cpus_over_the_node_blocks(self, sized_partitions):
        script = _sbatch("--cpus-per-task=64")
        intent = SubmitIntent(partition_name="stamps")
        findings = validate._check_resources(script, intent, sized_partitions)
        assert len(findings) == 1
        assert findings[0].check == "resources"
        assert findings[0].severity is Severity.BLOCKING
        assert "32" in findings[0].message

    def test_cpus_within_the_node_is_clean(self, sized_partitions):
        script = _sbatch("--cpus-per-task=8", "--mem=16G")
        intent = SubmitIntent(partition_name="stamps")
        assert validate._check_resources(script, intent, sized_partitions) == []

    def test_tasks_times_cpus_over_the_node_blocks(self, sized_partitions):
        script = _sbatch("--ntasks-per-node=8", "--cpus-per-task=8")
        intent = SubmitIntent(partition_name="stamps")
        findings = validate._check_resources(script, intent, sized_partitions)
        assert len(findings) == 1
        assert findings[0].check == "resources"
        assert "64" in findings[0].message

    def test_memory_over_the_node_blocks(self, sized_partitions):
        script = _sbatch("--mem=512G")
        intent = SubmitIntent(partition_name="stamps")
        findings = validate._check_resources(script, intent, sized_partitions)
        assert len(findings) == 1
        assert findings[0].check == "resources"
        assert "192000" in findings[0].message

    def test_memory_within_the_node_is_clean(self, sized_partitions):
        script = _sbatch("--mem=100G")
        intent = SubmitIntent(partition_name="stamps")
        assert validate._check_resources(script, intent, sized_partitions) == []

    def test_mem_per_cpu_totalled_over_the_node_blocks(self, sized_partitions):
        script = _sbatch("--cpus-per-task=16", "--mem-per-cpu=16G")
        intent = SubmitIntent(partition_name="stamps")
        findings = validate._check_resources(script, intent, sized_partitions)
        assert len(findings) == 1
        assert findings[0].check == "resources"

    def test_mem_per_cpu_within_the_node_is_clean(self, sized_partitions):
        script = _sbatch("--cpus-per-task=4", "--mem-per-cpu=4G")
        intent = SubmitIntent(partition_name="stamps")
        assert validate._check_resources(script, intent, sized_partitions) == []

    def test_an_unsized_partition_is_a_no_op(self, sized_partitions):
        # A probe cached before %c and %m were asked for reports zeroes.
        script = _sbatch("--cpus-per-task=999", "--mem=999G")
        intent = SubmitIntent(partition_name="unsized")
        assert validate._check_resources(script, intent, sized_partitions) == []

    def test_skipped_without_probe_data(self):
        script = _sbatch("--cpus-per-task=999")
        intent = SubmitIntent(partition_name="stamps")
        assert validate._check_resources(script, intent, None) == []
        assert validate._check_resources(script, intent, []) == []

    def test_skipped_when_no_partition_was_chosen(self, sized_partitions):
        script = _sbatch("--cpus-per-task=999")
        assert validate._check_resources(script, SubmitIntent(), sized_partitions) == []

    def test_skipped_when_the_partition_is_not_in_the_probe(self, sized_partitions):
        script = _sbatch("--cpus-per-task=999")
        intent = SubmitIntent(partition_name="not-probed")
        assert validate._check_resources(script, intent, sized_partitions) == []

    def test_reached_through_validate_script(self, sized_partitions, no_bash):
        script = _sbatch("--cpus-per-task=64")
        findings = validate_script(
            script,
            intent=SubmitIntent(partition_name="stamps"),
            partitions=sized_partitions,
        )
        assert any(f.check == "resources" for f in findings)
