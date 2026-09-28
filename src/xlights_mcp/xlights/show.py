"""Parse xLights show folder configuration files."""

from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from xlights_mcp.xlights.models import (
    Controller,
    LightModel,
    ModelGroup,
    ShowConfig,
    SubModel,
)

logger = logging.getLogger(__name__)


def load_show_config(show_path: Path) -> ShowConfig:
    """Load complete show configuration from an xLights show folder.

    Reads xlights_networks.xml and xlights_rgbeffects.xml to build
    a complete picture of the controllers, models, and groups.
    """
    controllers = load_show_controllers(show_path)
    models = load_show_models(show_path)
    groups, warnings = _load_groups(show_path, models)

    return ShowConfig(
        show_path=str(show_path),
        show_name=show_path.name,
        controllers=controllers,
        models=models,
        model_groups=groups,
        total_channels=sum(c.max_channels for c in controllers),
        warnings=warnings,
    )


def load_show_controllers(show_path: Path) -> list[Controller]:
    """Parse xlights_networks.xml to extract controller configuration."""
    networks_file = show_path / "xlights_networks.xml"
    if not networks_file.exists():
        logger.warning(f"Networks file not found: {networks_file}")
        return []

    tree = ET.parse(networks_file)
    root = tree.getroot()
    controllers = []

    for ctrl_elem in root.findall("Controller"):
        max_channels = 0
        for network in ctrl_elem.findall("network"):
            ch = network.get("MaxChannels", "0")
            try:
                max_channels += int(ch)
            except ValueError:
                pass

        controller = Controller(
            id=ctrl_elem.get("Id", ""),
            name=ctrl_elem.get("Name", ""),
            description=ctrl_elem.get("Description", ""),
            controller_type=ctrl_elem.get("Type", ""),
            vendor=ctrl_elem.get("Vendor", ""),
            model=ctrl_elem.get("Model", ""),
            ip=ctrl_elem.get("IP", ""),
            protocol=ctrl_elem.get("Protocol", ""),
            max_channels=max_channels,
            active_state=ctrl_elem.get("ActiveState", ""),
        )
        controllers.append(controller)

    logger.info(f"Loaded {len(controllers)} controllers from {networks_file}")
    return controllers


def load_show_models(show_path: Path) -> list[LightModel]:
    """Parse xlights_rgbeffects.xml to extract model definitions."""
    effects_file = show_path / "xlights_rgbeffects.xml"
    if not effects_file.exists():
        logger.warning(f"RGB effects file not found: {effects_file}")
        return []

    tree = ET.parse(effects_file)
    root = tree.getroot()
    models_elem = root.find("models")
    if models_elem is None:
        return []

    models = []
    for m in models_elem:
        if m.tag == "model":
            # Collect submodels (child elements)
            submodels = []
            face_definitions = []
            for child in m:
                if child.tag == "faceInfo":
                    face_name = child.get("Name", "")
                    if face_name:
                        face_definitions.append(face_name)
                    continue
                if child.tag in ("subModel", "strandNames", "nodeNames"):
                    continue
                child_name = child.get("name", "")
                if child_name:
                    submodels.append(SubModel(name=child_name, parent=m.get("name", "")))

            pixel_count = 0
            parm1 = m.get("parm1", "0")
            parm2 = m.get("parm2", "0")
            pixel_count_attr = m.get("PixelCount", "")
            if pixel_count_attr:
                try:
                    pixel_count = int(pixel_count_attr)
                except ValueError:
                    pass
            elif parm1 and parm2:
                try:
                    pixel_count = int(parm1) * int(parm2)
                except ValueError:
                    pass

            model = LightModel(
                name=m.get("name", ""),
                display_as=m.get("DisplayAs", ""),
                controller=m.get("Controller", ""),
                pixel_count=pixel_count,
                string_type=m.get("StringType", "RGB Nodes"),
                submodels=submodels,
                face_definitions=face_definitions,
                world_pos_y=_float_or_none(m.get("WorldPosY")),
            )
            models.append(model)

    logger.info(f"Loaded {len(models)} models from {effects_file}")
    return models


def load_model_groups(show_path: Path) -> list[ModelGroup]:
    """Parse and resolve model groups from xlights_rgbeffects.xml."""
    groups, _ = _load_groups(show_path, load_show_models(show_path))
    return groups


def _load_groups(show_path: Path, models: list[LightModel]) -> tuple[list[ModelGroup], list[str]]:
    effects_file = show_path / "xlights_rgbeffects.xml"
    if not effects_file.exists():
        return [], []
    root = ET.parse(effects_file).getroot()

    # xLights keeps groups in <modelGroups>; older files put them inside <models>.
    elements = []
    for container in ("modelGroups", "models"):
        parent = root.find(container)
        if parent is not None:
            elements.extend(e for e in parent if e.tag == "modelGroup")

    warnings: list[str] = []
    groups: dict[str, ModelGroup] = {}
    for e in elements:
        name = e.get("name", "").strip()
        if not name:
            continue
        if name in groups:
            warnings.append(f"Group '{name}' is defined more than once; using the first definition")
            continue
        groups[name] = ModelGroup(
            name=name,
            members=[n.strip() for n in e.get("models", "").split(",") if n.strip()],
            grid_size=e.get("GridSize", ""),
            layout=e.get("layout", ""),
        )

    all_model_names = {m.name for m in models}
    real_models = {m.name for m in models if not m.is_placeholder}
    for g in groups.values():
        g.child_groups = [m for m in g.members if m in groups]
        g.submodel_count = sum(_is_submodel_ref(m, groups, all_model_names) for m in g.members)
        g.has_submodels = g.submodel_count > 0
        for member in g.members:
            if (
                member not in groups
                and member not in all_model_names
                and not _is_submodel_ref(member, groups, all_model_names)
            ):
                warnings.append(f"Group '{g.name}' lists unknown member '{member}'")
    for g in groups.values():
        g.parent_groups = sorted(p.name for p in groups.values() if g.name in p.child_groups)
        g.leaf_models = sorted(_leaf_models(g.name, groups, real_models, all_model_names, ()))

    logger.info(f"Loaded {len(groups)} model groups from {effects_file}")
    return list(groups.values()), warnings


def _is_submodel_ref(member: str, groups: dict[str, ModelGroup], all_model_names: set[str]) -> bool:
    """True when `member` looks like "Model/Sub" and isn't itself a known model or group."""
    return (
        "/" in member
        and member not in all_model_names
        and member not in groups
        and member.split("/", 1)[0] in all_model_names
    )


def _leaf_models(
    name: str,
    groups: dict[str, ModelGroup],
    real_models: set[str],
    all_model_names: set[str],
    path: tuple[str, ...],
) -> set[str]:
    if name in path:  # a group nested inside itself
        return set()
    leaves: set[str] = set()
    for member in groups[name].members:
        if member in groups:
            leaves |= _leaf_models(member, groups, real_models, all_model_names, (*path, name))
            continue
        if member in all_model_names:
            model = member  # a real model name, even one containing "/"
        elif "/" in member:
            model = member.split("/", 1)[0]  # submodels count as their parent model
        else:
            continue  # unknown member; already warned about in _load_groups
        if model in real_models:
            leaves.add(model)
    return leaves


def _float_or_none(value: str | None) -> float | None:
    try:
        result = float(value) if value is not None else None
    except ValueError:
        return None
    return result if result is None or math.isfinite(result) else None
