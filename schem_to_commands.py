#!/usr/bin/env python3
"""
schem_to_commands.py

Converts a WorldEdit .schem file (Sponge Schematic format, v1/v2/v3) into a
list of Minecraft `setblock`/`fill` commands (with `data merge block` for
block entities such as chests/signs/command blocks), joined by ";" and
written to a .txt file - same convention used by generator/script.js.

The structure is anchored at the player: running the commands with the
player standing at the position captured by WorldEdit's //copy will
reproduce the structure around them, using relative (~ ~ ~) coordinates.

Usage:
    python schem_to_commands.py input.schem [-o output.txt] [options]

Options:
    -o, --output PATH      Output .txt path (default: <input>.txt)
    --include-air          Also place air blocks (clears the area first)
    --no-merge             Emit one setblock per block (skip fill merging)
    --no-slash             (default) commands have no leading "/"
    --slash                Prefix every command with "/"
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from nbt import Tag, TAG_COMPOUND, load as load_nbt
from snbt import compound_to_snbt

# =====================================================
# Default block-state stripping
# =====================================================
# Minecraft lets you omit block state properties that match the default
# value. Stripping them saves a LOT of characters in the output, which
# matters when there's a command-length limit.
#
# This table maps property names to their default values. A property
# whose current value matches its default can be silently dropped from
# the blockstate string without changing behaviour.
#
# Source: https://minecraft.wiki/w/Block_states (Java Edition)
# Covers every boolean, integer, and enum property that has a single
# universal default across all blocks that use it.

# Boolean properties that default to false
_BOOL_FALSE_DEFAULTS = {
    "waterlogged",  # slabs, stairs, fences, walls, signs, chains, ...
    "snowy",        # grass_block, podzol, mycelium
    "powered",      # buttons, pressure plates, rails, observers, ...
    "lit",          # furnace, redstone ore, redstone torch, campfire...
    "open",         # doors, fence gates, trapdoors, barrels
    "triggered",    # dispensers, droppers
    "inverted",     # daylight detector
    "extended",     # pistons
    "conditional",  # command blocks
    "disarmed",     # tripwire
    "attached",     # tripwire, tripwire hook
    "in_wall",      # fence gates
    "signal_fire",  # campfire
    "hanging",      # mangrove propagule, hanging signs
    "has_record",   # jukebox
    "has_book",     # lectern
    "eye",          # end portal frame
    "locked",       # repeater
    "unstable",     # TNT
    "occupied",     # beds
    "berries",      # cave vines
    "crafting",     # crafter
    "bloom",        # sculk catalyst
    "shrieking",    # sculk shrieker
    "can_summon",   # sculk shrieker
    "ominous",      # trial spawner, vault
    "bottom",       # scaffolding
    "drag",         # bubble column (default false = whirlpool)
    "cracked",      # turtle egg variants
    "short",        # piston head
    "up",           # walls, fire, vines, redstone wire
    "down",         # fire, vines
    "north",        # fire, vines, redstone wire, fences, glass panes, walls (bool variant)
    "south",        # fire, vines, redstone wire, fences, glass panes, walls (bool variant)
    "east",         # fire, vines, redstone wire, fences, glass panes, walls (bool variant)
    "west",         # fire, vines, redstone wire, fences, glass panes, walls (bool variant)
    "persistent",   # leaves (default false = decays naturally)
    "natural",      # beehive
    "enabled",      # hopper -- NOTE: hopper defaults to true, handled separately below
    "falling",      # fluid states
    "tip",          # pointed dripstone
    "slot_0_occupied",
    "slot_1_occupied",
    "slot_2_occupied",
    "slot_3_occupied",
    "slot_4_occupied",
    "slot_5_occupied",
    "has_bottle_0",
    "has_bottle_1",
    "has_bottle_2",
}

# Boolean properties that default to true (rare but they exist)
_BOOL_TRUE_DEFAULTS = {
    "enabled",      # hopper: default is true (enabled)
    "persistent",   # NOTE: leaves default is false, but some blocks...
}
# persistent defaults false, enabled defaults true — we handle them as
# special cases in the stripping logic below rather than trusting the
# sets above blindly. The canonical default is:
#   enabled -> true    (hopper)
#   persistent -> false (leaves)

# Non-boolean properties with well-known defaults
_ENUM_DEFAULTS = {
    "half": "lower",        # doors; for stairs/trapdoors it's "bottom" — see special handling
    "hinge": "left",        # doors
    "part": "foot",         # beds
    "shape": "straight",    # stairs, rails (but note rails use different values)
    "face": "wall",         # buttons, levers
    "attachment": "floor",  # bells
    "sculk_sensor_phase": "inactive",
    "trial_spawner_state": "inactive",
    "vault_state": "inactive",
    "creaking_heart_state": "disabled",
    "thickness": "tip",     # pointed dripstone
    "vertical_direction": "up",  # pointed dripstone
    "tilt": "none",         # big dripleaf
    "mode": "compare",      # comparator
    "orientation": "north_up",  # jigsaw
}

_INT_DEFAULTS = {
    "age": "0",
    "bites": "0",
    "candles": "1",
    "charges": "0",
    "delay": "1",
    "distance": "7",       # leaves
    "dusted": "0",
    "eggs": "1",
    "flower_amount": "1",
    "hatch": "0",
    "honey_level": "0",
    "layers": "1",          # snow
    "level": "0",           # water/lava cauldron; composter
    "moisture": "0",        # farmland
    "note": "0",
    "pickles": "1",
    "power": "0",
    "rotation": "0",
    "stage": "0",
    "segment_amount": "1",
}

# Wall-type blocks use "none" as default for side connections
_WALL_SIDE_DEFAULTS = {"none"}

# Regex to pull apart "minecraft:foo[a=b,c=d]" -> ("minecraft:foo", "a=b,c=d")
_BLOCKSTATE_RE = re.compile(r"^([^\[]+)\[([^\]]+)\]$")


def _strip_defaults(blockstate: str) -> str:
    """Remove block-state properties that match their default values."""
    m = _BLOCKSTATE_RE.match(blockstate)
    if not m:
        return blockstate  # no properties at all

    block_id = m.group(1)
    props_str = m.group(2)

    kept = []
    for prop in props_str.split(","):
        key, _, val = prop.partition("=")
        key = key.strip()
        val = val.strip()

        skip = False

        # --- boolean defaults ---
        if val == "false" and key in _BOOL_FALSE_DEFAULTS and key != "enabled":
            skip = True
        if val == "true" and key == "enabled":
            # hopper enabled=true is the default
            skip = True

        # --- numeric/enum defaults ---
        if not skip and key in _INT_DEFAULTS and val == _INT_DEFAULTS[key]:
            skip = True
        if not skip and key in _ENUM_DEFAULTS and val == _ENUM_DEFAULTS[key]:
            skip = True

        # --- wall side connections default to "none" ---
        if not skip and key in ("north", "south", "east", "west", "up") and val == "none":
            skip = True

        # --- type=normal / type=single / type=bottom defaults ---
        if not skip and key == "type":
            if val in ("normal", "single", "bottom"):
                skip = True

        # --- half: stairs/trapdoors default to "bottom", doors to "lower" ---
        if not skip and key == "half":
            if val == "bottom":
                skip = True
            elif val == "lower":
                skip = True

        # --- axis=y is default for logs, pillars, chains, etc. ---
        if not skip and key == "axis" and val == "y":
            skip = True

        # --- facing: most blocks default to "north" ---
        if not skip and key == "facing" and val == "north":
            skip = True

        # --- level defaults ---
        if not skip and key == "level" and val == "0":
            skip = True

        if not skip:
            kept.append(prop)

    if not kept:
        return block_id
    return f"{block_id}[{','.join(kept)}]"


class Schematic:
    def __init__(self, width, height, length, offset, blocks, block_entities):
        self.width = width
        self.height = height
        self.length = length
        self.offset = offset  # (ox, oy, oz)
        self.blocks = blocks  # dict[(x,y,z)] -> blockstate string ("minecraft:air" included)
        self.block_entities = block_entities  # dict[(x,y,z)] -> Tag (TAG_COMPOUND)


def _to_unsigned16(value: int) -> int:
    return value & 0xFFFF


def _read_varints(byte_values, count):
    """Decode `count` unsigned LEB128 varints from a list of (signed) bytes."""
    values = []
    i = 0
    n = len(byte_values)
    for _ in range(count):
        value = 0
        shift = 0
        while True:
            if i >= n:
                raise EOFError("BlockData ended before all blocks were read")
            b = byte_values[i] & 0xFF
            i += 1
            value |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        values.append(value)
    return values


def _pos_of(entity_tag: Tag):
    pos_tag = entity_tag.get("Pos")
    if pos_tag is None:
        return None
    x, y, z = pos_tag.unwrap()
    return (x, y, z)


def parse_schematic(path: str) -> Schematic:
    _, root = load_nbt(path)
    if root.id != TAG_COMPOUND:
        raise ValueError("Root NBT tag is not a compound - not a valid .schem file")

    data = root
    # Some tools nest everything under a "Schematic" compound.
    if "Schematic" in data.value and "Blocks" not in data.value and "Palette" not in data.value:
        data = data.value["Schematic"]

    version_tag = data.get("Version")
    version = version_tag.unwrap() if version_tag is not None else 2

    if version == 3:
        blocks_tag = data.get("Blocks")
        if blocks_tag is None:
            raise ValueError("Version 3 schematic missing 'Blocks' compound")
        palette_tag = blocks_tag.get("Palette")
        data_tag = blocks_tag.get("Data")
        entities_tag = blocks_tag.get("BlockEntities")
    else:
        palette_tag = data.get("Palette")
        data_tag = data.get("BlockData")
        entities_tag = data.get("BlockEntities") or data.get("TileEntities")

    if palette_tag is None or data_tag is None:
        raise ValueError("Could not find Palette/BlockData in schematic (unsupported format?)")

    width = _to_unsigned16(data.get("Width").unwrap())
    height = _to_unsigned16(data.get("Height").unwrap())
    length = _to_unsigned16(data.get("Length").unwrap())

    # The anchor point (where local (0,0,0) ends up relative to the player)
    # is *not* the top-level "Offset" tag: WorldEdit writes that as the
    # schematic's absolute world-space min corner at the time of //copy,
    # which is meaningless once pasted elsewhere. The value we actually
    # want - "min corner minus player position at copy time" - is stored
    # in Metadata.WEOffsetX/Y/Z (a legacy field WorldEdit still writes for
    # every .schem it produces). Fall back to the spec-compliant top-level
    # Offset only for files that don't have WorldEdit metadata (e.g. ones
    # generated by other tools that follow the Sponge spec literally).
    offset = None
    metadata_tag = data.get("Metadata")
    if metadata_tag is not None and metadata_tag.id == TAG_COMPOUND:
        wex = metadata_tag.get("WEOffsetX")
        wey = metadata_tag.get("WEOffsetY")
        wez = metadata_tag.get("WEOffsetZ")
        if wex is not None and wey is not None and wez is not None:
            offset = (wex.unwrap(), wey.unwrap(), wez.unwrap())
    if offset is None:
        offset_tag = data.get("Offset")
        offset = tuple(offset_tag.unwrap()) if offset_tag is not None else (0, 0, 0)

    palette = palette_tag.unwrap()  # dict[blockstate string] -> int id
    # Strip default block-state properties at the palette level (done once
    # per unique block type, saves many characters in the final output).
    palette_inv = {v: _strip_defaults(k) for k, v in palette.items()}

    raw_bytes = data_tag.value  # list[int] signed bytes
    total = width * height * length
    indices = _read_varints(raw_bytes, total)

    blocks = {}
    for y in range(height):
        for z in range(length):
            base = z * width + y * width * length
            for x in range(width):
                idx = indices[base + x]
                blockstate = palette_inv.get(idx, "minecraft:air")
                blocks[(x, y, z)] = blockstate

    block_entities = {}
    if entities_tag is not None:
        _, items = entities_tag.value
        for entity in items:
            pos = _pos_of(entity)
            if pos is not None:
                block_entities[pos] = entity

    return Schematic(width, height, length, offset, blocks, block_entities)


def _strip_aggressive(blockstate: str) -> str:
    """For aggressive mode: strip distance, age, level properties too."""
    m = _BLOCKSTATE_RE.match(blockstate)
    if not m:
        return blockstate
    block_id = m.group(1)
    props_str = m.group(2)
    kept = []
    for prop in props_str.split(","):
        key = prop.partition("=")[0].strip()
        if key in ("distance", "age", "level", "moisture", "stage",
                    "honey_level", "hatch", "dusted", "charges"):
            continue
        kept.append(prop)
    if not kept:
        return block_id
    return f"{block_id}[{','.join(kept)}]"


def generate_commands(schem: Schematic, include_air: bool, merge: bool,
                      absolute_origin: "tuple[int,int,int] | None" = None,
                      aggressive: bool = False):
    ox, oy, oz = schem.offset
    width, height, length = schem.width, schem.height, schem.length

    if absolute_origin is not None:
        # Absolute mode: anchor is the user-provided world coordinate,
        # offset by the schematic's WEOffset so blocks land correctly.
        bx, by, bz = absolute_origin

        def coord(x, y, z):
            return f"{bx + ox + x} {by + oy + y} {bz + oz + z}"
    else:
        def coord(x, y, z):
            return f"~{ox + x} ~{oy + y} ~{oz + z}"

    commands = []

    # Positions that must be emitted individually (they carry block-entity
    # NBT data, so they can't be merged into a fill).
    entity_positions = set(schem.block_entities.keys())

    # In aggressive mode, block entities are treated as regular blocks
    # (their NBT data is stripped), so they CAN be merged into fills.
    if aggressive:
        entity_positions = set()

    visited = [[[False] * length for _ in range(height)] for _ in range(width)]

    def is_air(blockstate: str) -> bool:
        return blockstate in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")

    def block_at(x, y, z):
        bs = schem.blocks.get((x, y, z), "minecraft:air")
        if aggressive:
            bs = _strip_aggressive(bs)
        return bs

    def usable(x, y, z, blockstate):
        if visited[x][y][z]:
            return False
        if (x, y, z) in entity_positions:
            return False
        b = block_at(x, y, z)
        if b != blockstate:
            return False
        if not include_air and is_air(b):
            return False
        return True

    # 1) Individual setblocks for block entities (chests, signs, command
    #    blocks, etc.) so their NBT data is preserved.
    if not aggressive:
        for (bex, bey, bez), entity in schem.block_entities.items():
            blockstate = block_at(bex, bey, bez)
            visited[bex][bey][bez] = True
            if not include_air and is_air(blockstate):
                continue
            commands.append(f"setblock {coord(bex, bey, bez)} {blockstate}")
            snbt = compound_to_snbt(entity, exclude={"Id", "Pos", "id", "pos"})
            if snbt != "{}":
                commands.append(f"data merge block {coord(bex, bey, bez)} {snbt}")

    # 2) Greedy box merging for the rest of the blocks.
    for y in range(height):
        for z in range(length):
            for x in range(width):
                if visited[x][y][z] or (x, y, z) in entity_positions:
                    continue
                blockstate = block_at(x, y, z)
                if not include_air and is_air(blockstate):
                    visited[x][y][z] = True
                    continue

                if not merge:
                    visited[x][y][z] = True
                    commands.append(f"setblock {coord(x, y, z)} {blockstate}")
                    continue

                # Extend along X.
                x2 = x
                while x2 + 1 < width and usable(x2 + 1, y, z, blockstate):
                    x2 += 1

                # Extend the X-run along Z.
                z2 = z
                while z2 + 1 < length and all(
                    usable(xi, y, z2 + 1, blockstate) for xi in range(x, x2 + 1)
                ):
                    z2 += 1

                # Extend the X-Z rectangle along Y.
                y2 = y
                while y2 + 1 < height and all(
                    usable(xi, y2 + 1, zi, blockstate)
                    for xi in range(x, x2 + 1)
                    for zi in range(z, z2 + 1)
                ):
                    y2 += 1

                for yi in range(y, y2 + 1):
                    for zi in range(z, z2 + 1):
                        for xi in range(x, x2 + 1):
                            visited[xi][yi][zi] = True

                if (x, y, z) == (x2, y2, z2):
                    commands.append(f"setblock {coord(x, y, z)} {blockstate}")
                else:
                    commands.append(
                        f"fill {coord(x, y, z)} {coord(x2, y2, z2)} {blockstate}"
                    )

    return commands


def _parse_coords(s: str) -> "tuple[int,int,int] | None":
    """Parse 'x y z' into (int, int, int) or None."""
    parts = s.strip().split()
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the .schem file")
    parser.add_argument("-o", "--output", help="Output .txt path (default: <input>.txt)")
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Skip the interactive TUI and use CLI flags only",
    )
    parser.add_argument(
        "--include-air",
        action="store_true",
        help="Also place air blocks (clears the target area before building)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Disable fill merging; emit one setblock per block",
    )
    parser.add_argument(
        "--slash",
        action="store_true",
        help='Prefix every command with "/" (for pasting directly into chat)',
    )
    parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Strip block entity NBT, distance, age, level, etc.",
    )
    parser.add_argument(
        "--origin",
        type=str,
        default=None,
        help='Absolute origin coords "X Y Z" (default: player-relative ~ ~ ~)',
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    # Default output goes into an "output" subfolder next to the script
    if args.output:
        output = args.output
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(script_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(args.input))[0] + ".txt"
        output = os.path.join(out_dir, base)

    # Parse schematic first so the TUI can show info
    schem = parse_schematic(args.input)
    schem_name = os.path.basename(args.input)
    schem_info = (f"{schem.width}x{schem.height}x{schem.length}  "
                  f"{len(schem.block_entities)} block entities")

    if not args.no_tui and sys.stdin.isatty() and sys.stdout.isatty():
        from tui import run_tui
        opts = run_tui(schem_name, schem_info)
        if opts is None:
            print("Cancelled.")
            return 1

        include_air = opts.include_air
        no_merge = opts.no_merge
        slash = opts.slash
        aggressive = opts.aggressive
        if opts.use_relative:
            absolute_origin = None
        else:
            absolute_origin = _parse_coords(opts.abs_coords)
            if absolute_origin is None:
                print("error: invalid coordinates", file=sys.stderr)
                return 1
    else:
        include_air = args.include_air
        no_merge = args.no_merge
        slash = args.slash
        aggressive = args.aggressive
        absolute_origin = _parse_coords(args.origin) if args.origin else None

    commands = generate_commands(
        schem,
        include_air=include_air,
        merge=not no_merge,
        absolute_origin=absolute_origin,
        aggressive=aggressive,
    )

    if slash:
        commands = [f"/{c}" for c in commands]

    with open(output, "w", encoding="utf-8") as f:
        f.write(";".join(commands))

    total_chars = sum(len(c) for c in commands) + max(0, len(commands) - 1)
    print(f"\n  Parsed {schem.width}x{schem.height}x{schem.length} schematic "
          f"({len(schem.blocks)} blocks, {len(schem.block_entities)} block entities)")
    print(f"  Wrote {len(commands)} commands ({total_chars:,} chars) to {output}")
    if aggressive:
        print(f"  Aggressive mode: block entity NBT and transient states stripped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
