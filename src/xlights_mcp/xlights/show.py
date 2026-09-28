"""Parse xLights show folder configuration files."""

from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
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
    root = _load_effects_root(show_path)
    models = _parse_models(root)
    groups, warnings = _load_groups(root, models)

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


def _load_effects_root(show_path: Path) -> ET.Element:
    """Root of xlights_rgbeffects.xml, or an empty element when the file is missing."""
    effects_file = show_path / "xlights_rgbeffects.xml"
    if not effects_file.exists():
        logger.warning(f"RGB effects file not found: {effects_file}")
        return ET.Element("xrgb")
    return ET.parse(effects_file).getroot()


def load_show_models(show_path: Path) -> list[LightModel]:
    """Parse xlights_rgbeffects.xml to extract model definitions."""
    return _parse_models(_load_effects_root(show_path))


def _parse_models(root: ET.Element) -> list[LightModel]:
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

    logger.info(f"Loaded {len(models)} models")
    return models


def load_model_groups(show_path: Path) -> list[ModelGroup]:
    """Parse and resolve model groups from xlights_rgbeffects.xml."""
    root = _load_effects_root(show_path)
    groups, _ = _load_groups(root, _parse_models(root))
    return groups


def _load_groups(root: ET.Element, models: list[LightModel]) -> tuple[list[ModelGroup], list[str]]:
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
    parents: defaultdict[str, set[str]] = defaultdict(set)
    for g in groups.values():
        for member in g.members:
            if member in groups:
                g.child_groups.append(member)
                parents[member].add(g.name)
            elif member in all_model_names:
                continue
            elif _is_submodel_ref(member, all_model_names):
                g.submodel_count += 1
            else:
                warnings.append(f"Group '{g.name}' lists unknown member '{member}'")

    real_models = {m.name for m in models if not m.is_placeholder}
    leaves_of = _leaf_resolver(groups, real_models, all_model_names)
    for g in groups.values():
        g.parent_groups = sorted(parents[g.name])
        g.leaf_models = sorted(leaves_of(g.name))

    logger.info(f"Loaded {len(groups)} model groups")
    return list(groups.values()), warnings


def _is_submodel_ref(member: str, all_model_names: set[str]) -> bool:
    """True when `member` looks like "Model/Sub" for a known model."""
    return "/" in member and member.split("/", 1)[0] in all_model_names


def _leaf_resolver(
    groups: dict[str, ModelGroup], real_models: set[str], all_model_names: set[str]
) -> Callable[[str], set[str]]:
    """Function giving the real models each group reaches through nesting, memoized per group."""
    memo: dict[str, set[str]] = {}
    cycle_cuts = 0

    def resolve(name: str, path: tuple[str, ...]) -> set[str]:
        nonlocal cycle_cuts
        if name in memo:
            return memo[name]
        if name in path:
            cycle_cuts += 1
            return set()
        cuts_before = cycle_cuts
        leaves: set[str] = set()
        for member in groups[name].members:
            if member in groups:
                leaves |= resolve(member, (*path, name))
                continue
            if member in all_model_names:
                model = member
            elif "/" in member:
                model = member.split("/", 1)[0]
            else:
                continue
            if model in real_models:
                leaves.add(model)
        if cycle_cuts == cuts_before:
            memo[name] = leaves
        return leaves

    return lambda name: resolve(name, ())


def _float_or_none(value: str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
