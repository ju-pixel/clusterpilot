"""Tests for params_table.py: parsing, validation, and the bash reader."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from clusterpilot.jobs.params_table import (
    ParamsTable,
    ParamsTableError,
    describe_for_prompt,
    load_params_table,
    render_bash_reader,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


# ── loading ───────────────────────────────────────────────────────────────────

class TestLoad:
    def test_tsv_round_trip(self, tmp_path):
        path = _write(tmp_path, "p.tsv", """
            lattice\teta\tsamples
            fcc\t0.30\t512
            bcc\t0.15\t512
        """)
        table = load_params_table(path)
        assert table.headers == ["lattice", "eta", "samples"]
        assert table.rows == [["fcc", "0.30", "512"], ["bcc", "0.15", "512"]]
        assert table.task_count == 2
        assert table.array_spec == "0-1"

    def test_csv_round_trip(self, tmp_path):
        path = _write(tmp_path, "p.csv", """
            alpha,beta
            1,2
        """)
        table = load_params_table(path)
        assert table.headers == ["alpha", "beta"]
        assert table.task_count == 1
        assert table.array_spec == "0-0"

    def test_blank_lines_are_not_tasks(self, tmp_path):
        path = _write(tmp_path, "p.csv", """
            a,b
            1,2

            3,4

        """)
        assert load_params_table(path).task_count == 2

    def test_cells_are_stripped(self, tmp_path):
        path = _write(tmp_path, "p.csv", "a,b\n 1 , 2 \n")
        assert load_params_table(path).rows == [["1", "2"]]

    def test_row_for_returns_a_mapping(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "x\ty\n1\t2\n3\t4\n")
        table = load_params_table(path)
        assert table.row_for(0) == {"x": "1", "y": "2"}
        assert table.row_for(1) == {"x": "3", "y": "4"}

    def test_row_for_rejects_out_of_range(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "x\n1\n")
        table = load_params_table(path)
        with pytest.raises(ParamsTableError, match="outside the table"):
            table.row_for(1)


# ── rejection ─────────────────────────────────────────────────────────────────

class TestRejects:
    def test_unknown_extension(self, tmp_path):
        path = _write(tmp_path, "p.txt", "a\n1\n")
        with pytest.raises(ParamsTableError, match="unsupported extension"):
            load_params_table(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(ParamsTableError, match="cannot read"):
            load_params_table(tmp_path / "absent.csv")

    def test_empty_file(self, tmp_path):
        path = _write(tmp_path, "p.csv", "\n")
        with pytest.raises(ParamsTableError, match="is empty"):
            load_params_table(path)

    def test_header_only(self, tmp_path):
        path = _write(tmp_path, "p.csv", "a,b\n")
        with pytest.raises(ParamsTableError, match="no data rows"):
            load_params_table(path)

    def test_ragged_row(self, tmp_path):
        path = _write(tmp_path, "p.csv", "a,b\n1,2\n3\n")
        with pytest.raises(ParamsTableError, match="line 3"):
            load_params_table(path)

    def test_header_starting_with_a_digit(self, tmp_path):
        path = _write(tmp_path, "p.csv", "2theta,b\n1,2\n")
        with pytest.raises(ParamsTableError, match="not a valid shell identifier"):
            load_params_table(path)

    def test_header_with_a_hyphen(self, tmp_path):
        path = _write(tmp_path, "p.csv", "my-col,b\n1,2\n")
        with pytest.raises(ParamsTableError, match="not a valid shell identifier"):
            load_params_table(path)

    def test_blank_header_cell(self, tmp_path):
        path = _write(tmp_path, "p.csv", "a,,c\n1,2,3\n")
        with pytest.raises(ParamsTableError, match="blank column name"):
            load_params_table(path)

    def test_duplicate_headers(self, tmp_path):
        path = _write(tmp_path, "p.csv", "a,a\n1,2\n")
        with pytest.raises(ParamsTableError, match="duplicate column name"):
            load_params_table(path)

    def test_reserved_header_is_refused(self, tmp_path):
        path = _write(tmp_path, "p.csv", "PATH,b\n1,2\n")
        with pytest.raises(ParamsTableError, match="overwrite an environment variable"):
            load_params_table(path)

    def test_reserved_header_is_case_insensitive(self, tmp_path):
        path = _write(tmp_path, "p.csv", "home,b\n1,2\n")
        with pytest.raises(ParamsTableError, match="overwrite an environment variable"):
            load_params_table(path)


# ── the bash reader, exercised for real ───────────────────────────────────────

class TestBashReader:
    def _run(self, tmp_path: Path, table: ParamsTable, task_id: int):
        """Run the rendered reader under bash and dump the exported variables."""
        script = tmp_path / "run.sh"
        body = "#!/bin/bash\nset -u\n" + render_bash_reader(table)
        body += "\n".join(f'echo "{h}=${h}"' for h in table.headers) + "\n"
        script.write_text(body, encoding="utf-8")
        return subprocess.run(
            ["bash", str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "SLURM_ARRAY_TASK_ID": str(task_id)},
        )

    def test_tsv_reader_exports_the_right_row(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "lattice\teta\nfcc\t0.30\nbcc\t0.15\n")
        table = load_params_table(path)
        first = self._run(tmp_path, table, 0)
        assert first.returncode == 0, first.stderr
        assert "lattice=fcc" in first.stdout
        assert "eta=0.30" in first.stdout
        second = self._run(tmp_path, table, 1)
        assert "lattice=bcc" in second.stdout
        assert "eta=0.15" in second.stdout

    def test_csv_reader_exports_the_right_row(self, tmp_path):
        path = _write(tmp_path, "p.csv", "alpha,beta\n1,2\n3,4\n")
        table = load_params_table(path)
        result = self._run(tmp_path, table, 1)
        assert result.returncode == 0, result.stderr
        assert "alpha=3" in result.stdout
        assert "beta=4" in result.stdout

    def test_reader_fails_loudly_on_an_out_of_range_index(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "x\n1\n")
        table = load_params_table(path)
        result = self._run(tmp_path, table, 5)
        assert result.returncode != 0
        assert "no row for SLURM_ARRAY_TASK_ID=5" in result.stderr

    def test_reader_fails_loudly_when_the_table_is_absent(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "x\n1\n")
        table = load_params_table(path)
        path.unlink()
        result = self._run(tmp_path, table, 0)
        assert result.returncode != 0
        assert "not found" in result.stderr


class TestPromptDescription:
    def test_names_the_columns_and_the_count_but_not_the_rows(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "lattice\teta\nfcc\t0.30\nbcc\t0.15\n")
        text = describe_for_prompt(load_params_table(path))
        assert "p.tsv" in text
        assert "2 data rows" in text
        assert "lattice, eta" in text
        assert "fcc" not in text


# ── the prompt section built from a table ─────────────────────────────────────

class TestPromptIntegration:
    """The table must reach the system prompt as a verbatim block, not prose."""

    def _prompt(self, tmp_path, table):
        from clusterpilot.cluster.probe import ClusterProbe
        from clusterpilot.config import ClusterProfile
        from clusterpilot.jobs.ai_gen import _build_system_prompt

        probe = ClusterProbe(
            cluster_name="test", probed_at=0.0, partitions=[],
            julia_versions=[], accounts=[], account_max_wall={},
        )
        profile = ClusterProfile(
            name="test", host="h", user="u", account="acct", scratch="/scratch/u",
        )
        return _build_system_prompt(
            probe=probe, profile=profile, partition="", array_spec=table.array_spec,
            params_table=table,
        )

    def test_reader_block_is_embedded_verbatim(self, tmp_path):
        path = _write(tmp_path, "p.tsv", "lattice\teta\nfcc\t0.30\nbcc\t0.15\n")
        table = load_params_table(path)
        prompt = self._prompt(tmp_path, table)
        # The exact bash the script must contain, not a description of it.
        assert 'export lattice=' in prompt
        assert 'export eta=' in prompt
        assert "SLURM_ARRAY_TASK_ID" in prompt
        assert "p.tsv" in prompt

    def test_prompt_forbids_the_model_inventing_a_mapping(self, tmp_path):
        path = _write(tmp_path, "p.csv", "a,b\n1,2\n")
        prompt = self._prompt(tmp_path, load_params_table(path))
        assert "case statement" in prompt
        assert "the table IS the" in prompt

    def test_no_table_means_no_section(self, tmp_path):
        from clusterpilot.cluster.probe import ClusterProbe
        from clusterpilot.config import ClusterProfile
        from clusterpilot.jobs.ai_gen import _build_system_prompt

        probe = ClusterProbe(
            cluster_name="test", probed_at=0.0, partitions=[],
            julia_versions=[], accounts=[], account_max_wall={},
        )
        profile = ClusterProfile(
            name="test", host="h", user="u", account="acct", scratch="/scratch/u",
        )
        prompt = _build_system_prompt(probe=probe, profile=profile)
        assert "PARAMETER TABLE" not in prompt
