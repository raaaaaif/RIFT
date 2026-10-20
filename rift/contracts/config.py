"""Frozen architecture configuration contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rift.contracts.canonical import digest, read_json
from rift.paths import CONFIGS

TOPOLOGY_CODES = {"LIC": 0, "BFLY2": 1, "BFLY4": 2}

FIXED_FIELDS = {
    "addr_width": 32,
    "data_width": 32,
    "byte_off_width": 2,
    "be_width": 4,
    "resp_lat": 1,
    "write_resp_on": 1,
    "num_par": 1,
    "capacity_words": 4096,
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ArchConfig:
    raw: dict

    @property
    def config_id(self) -> str:
        return self.raw["config_id"]

    @property
    def topology(self) -> str:
        return self.raw["topology"]

    @property
    def topology_code(self) -> int:
        return TOPOLOGY_CODES[self.topology]

    @property
    def num_in(self) -> int:
        return self.raw["num_in"]

    @property
    def num_out(self) -> int:
        return self.raw["num_out"]

    @property
    def addr_mem_width(self) -> int:
        return self.raw["addr_mem_width"]

    @property
    def capacity_words(self) -> int:
        return self.raw["capacity_words"]

    @property
    def digest(self) -> str:
        return digest(self.raw)

    def bank(self, byte_address: int) -> int:
        return (byte_address >> 2) % self.num_out

    def row(self, byte_address: int) -> int:
        return (byte_address >> 2) // self.num_out


def validate_config(raw: dict) -> ArchConfig:
    if raw.get("schema_version") != 1:
        raise ConfigError("unsupported configuration schema_version")
    for k, v in FIXED_FIELDS.items():
        if raw.get(k) != v:
            raise ConfigError(f"{k} must be {v} for the Phase 0 contract (got {raw.get(k)!r})")
    if raw.get("topology") not in TOPOLOGY_CODES:
        raise ConfigError("topology must be LIC, BFLY2 or BFLY4")
    ni, no, amw = raw.get("num_in"), raw.get("num_out"), raw.get("addr_mem_width")
    for name, v in (("num_in", ni), ("num_out", no), ("addr_mem_width", amw)):
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ConfigError(f"{name} must be a positive integer")
    if no * (1 << amw) != raw["capacity_words"]:
        raise ConfigError("num_out * 2**addr_mem_width must equal capacity_words (4096)")
    if raw["topology"] != "LIC":
        if ni & (ni - 1) or no & (no - 1) or no < ni:
            raise ConfigError("butterfly topologies need power-of-two NumIn <= NumOut")
    if not isinstance(raw.get("config_id"), str) or not raw["config_id"]:
        raise ConfigError("config_id required")
    return ArchConfig(raw)


def load_config(ref: str | Path) -> ArchConfig:
    p = Path(ref)
    if not p.suffix:
        p = CONFIGS / f"{ref}.json"
    elif not p.is_absolute() and not p.exists():
        p = CONFIGS / p.name
    return validate_config(read_json(p))
