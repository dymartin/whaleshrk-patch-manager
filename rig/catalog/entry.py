"""The catalog entry: one per module, written to `.rig/catalog/<key-safe>.json`.

Schema is this task's design -- docs/catalog.md specifies what an entry must
carry (key, moduleType, category + override, tags, parameters with slug/id/
min/max/default/type, version/hash) without pinning an exact JSON shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .params import ParamSpec

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VersionInfo:
    """Community-only: absent (None fields) for @orhack built-ins.

    `revision` is deliberately not stored -- author free text, unusable as a
    version (docs/catalog.md "Versioning").
    """

    updated_at: str | None = None
    file_id: int | None = None
    archive_sha256: str | None = None


@dataclass(frozen=True)
class CatalogEntry:
    key: str  # slug(display)@source
    source: str  # "orhack" or the Patchstorage upload slug
    display: str
    module_type: str  # runtime path, resolved against userModuleDir then modules/
    category: str | None  # ORHACK install folder, e.g. "instruments/synth"; None for @orhack
    category_override: str | None
    tags: list[str]
    params: list[ParamSpec]
    version: VersionInfo
    sidecar_templates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "key": self.key,
            "source": self.source,
            "display": self.display,
            "moduleType": self.module_type,
            "category": self.category,
            "category_override": self.category_override,
            "tags": list(self.tags),
            "params": [
                {
                    "name": p.name,
                    "id": p.id,
                    "label": p.label,
                    "type": p.type,
                    "min": p.min,
                    "max": p.max,
                    "default": p.default,
                }
                for p in self.params
            ],
            "version": {
                "updated_at": self.version.updated_at,
                "file_id": self.version.file_id,
                "archive_sha256": self.version.archive_sha256,
            },
            "sidecar_templates": list(self.sidecar_templates),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CatalogEntry":
        return CatalogEntry(
            key=data["key"],
            source=data["source"],
            display=data["display"],
            module_type=data["moduleType"],
            category=data["category"],
            category_override=data.get("category_override"),
            tags=list(data.get("tags", [])),
            params=[
                ParamSpec(
                    name=p["name"],
                    id=p["id"],
                    label=p["label"],
                    type=p["type"],
                    min=p["min"],
                    max=p["max"],
                    default=p["default"],
                )
                for p in data.get("params", [])
            ],
            version=VersionInfo(**data.get("version", {})),
            sidecar_templates=list(data.get("sidecar_templates", [])),
        )


def entry_filename(key: str) -> str:
    """Filesystem-safe filename for a catalog entry -- '@' and '/' cannot appear in one."""
    return key.replace("@", "__").replace("/", "-") + ".json"
