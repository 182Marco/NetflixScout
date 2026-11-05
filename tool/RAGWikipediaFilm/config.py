"""Typed loader of config.yaml (pydantic, no defaults hidden in the code)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_DIR / "config.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DumpConfig(_Section):
    date: str
    base_url: str
    filename_template: str
    sha1sums_template: str
    raw_dir: str
    timeout_seconds: float
    chunk_bytes: int
    max_retries: int
    retry_backoff_seconds: float

    @property
    def filename(self) -> str:
        return self.filename_template.format(date=self.date)

    @property
    def url(self) -> str:
        return f"{self.base_url}/{self.date}/{self.filename}"

    @property
    def sha1sums_url(self) -> str:
        return f"{self.base_url}/{self.date}/{self.sha1sums_template.format(date=self.date)}"


class ExtractConfig(_Section):
    processed_dir: str
    min_plot_chars: int
    min_plot_words: int
    checkpoint_every_pages: int
    plot_headings: list[str]
    film_templates: list[str]
    disambiguation_templates: list[str]
    excluded_title_prefixes: list[str]


class WikidataConfig(_Section):
    api_url: str
    sparql_url: str
    site: str
    contact: str
    user_agent_name: str
    batch_size: int
    min_interval_seconds: float
    timeout_seconds: float
    sparql_timeout_seconds: float
    label_batch_size: int
    max_retries: int
    retry_backoff_seconds: float
    maxlag: int
    languages: list[str]
    mode: str
    snapshot_id: str
    snapshot_root: str
    max_actors: int


class OutputConfig(_Section):
    films_file: str
    candidates_file: str
    rejected_file: str
    manifest_dir: str


class PipelineConfig(_Section):
    dump: DumpConfig
    extract: ExtractConfig
    wikidata: WikidataConfig
    output: OutputConfig

    def path(self, relative: str) -> Path:
        return PACKAGE_DIR / relative

    @property
    def dump_path(self) -> Path:
        return self.path(self.dump.raw_dir) / self.dump.filename

    @property
    def processed_dir(self) -> Path:
        return self.path(self.extract.processed_dir)

    @property
    def snapshot_dir(self) -> Path:
        return self.path(self.wikidata.snapshot_root) / self.wikidata.snapshot_id

    @property
    def dump_timestamp(self) -> str:
        """`retrieved_at` of every record: the dump date, never the wall clock (determinism)."""
        d = self.dump.date
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}T00:00:00Z"


def load_config(path: Path | str | None = None, overrides: dict[str, Any] | None = None) -> PipelineConfig:
    raw = yaml.safe_load(Path(path or DEFAULT_CONFIG).read_text(encoding="utf-8"))
    for dotted, value in (overrides or {}).items():
        node = raw
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return PipelineConfig.model_validate(raw)


def config_sha256(path: Path | str | None = None) -> str:
    return hashlib.sha256(Path(path or DEFAULT_CONFIG).read_bytes()).hexdigest()
