#!/usr/bin/env python3
"""
Interpret a SAT solver's satisfying assignment in terms of the original
C program variables using CBMC's DIMACS mapping comments.

Usage:
    python interpret_sat_assignment.py <dimacs_file> <assignment_file>

The assignment file should contain space-separated literals (positive = true, negative = false),
ending with 0, as output by most SAT solvers (e.g., MiniSat, CaDiCaL).

Example assignment file content:
    1 -2 3 4 -5 6 ... 0

Or the "v" lines from SAT solver output:
    v 1 -2 3 4 -5 6 ...
    v 7 8 -9 ...
    v 0
"""

import sys
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class VariableMapping:
    """Mapping from an SSA variable to its DIMACS literals."""
    name: str
    literals: List[int]  # List of DIMACS variable numbers (positive)
    type_info: str       # Type string like "signedbv[32]"
    width: Optional[int] = None
    is_signed: Optional[bool] = None


def parse_type_info(type_str: str) -> Tuple[Optional[int], Optional[bool]]:
    """Parse type string to extract width and signedness."""
    # Match patterns like "signedbv[32]", "unsignedbv[64]"
    match = re.match(r'(signed|unsigned)bv\[(\d+)\]', type_str)
    if match:
        is_signed = match.group(1) == 'signed'
        width = int(match.group(2))
        return width, is_signed
    return None, None


def parse_dimacs_comments(dimacs_file: str) -> Dict[str, VariableMapping]:
    """Parse DIMACS file and extract variable mappings from comments."""
    mappings = {}

    with open(dimacs_file, 'r') as f:
        for line in f:
            if not line.startswith('c '):
                continue

            # Remove the 'c ' prefix
            content = line[2:].strip()
            if not content:
                continue

            # Check for @type= suffix
            type_match = re.search(r'@type=(\S+)$', content)
            type_info = type_match.group(1) if type_match else "unknown"

            # Remove the type info from content for parsing
            if type_match:
                content = content[:type_match.start()].strip()

            # Split into variable name and literals
            parts = content.split()
            if len(parts) < 2:
                continue

            var_name = parts[0]

            # Parse literals (can be numbers, TRUE, or FALSE)
            literals = []
            for part in parts[1:]:
                if part == 'TRUE':
                    literals.append('TRUE')
                elif part == 'FALSE':
                    literals.append('FALSE')
                else:
                    try:
                        # DIMACS literal (can be negative for negated)
                        lit = int(part)
                        literals.append(abs(lit))  # Store the variable number
                    except ValueError:
                        continue

            if literals:
                width, is_signed = parse_type_info(type_info)
                mappings[var_name] = VariableMapping(
                    name=var_name,
                    literals=literals,
                    type_info=type_info,
                    width=width,
                    is_signed=is_signed
                )

    return mappings


def parse_sat_assignment(assignment_file: str) -> Dict[int, bool]:
    """
    Parse SAT solver output to get variable assignments.
    Returns a dict mapping variable number to True/False.
    """
    assignment = {}

    with open(assignment_file, 'r') as f:
        content = f.read()

    # Handle different SAT solver output formats
    # Format 1: Just literals separated by spaces, ending with 0
    # Format 2: Lines starting with 'v' followed by literals

    literals = []

    # Check if it's the 'v' line format
    if 'v ' in content or content.startswith('v'):
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('v '):
                parts = line[2:].split()
                literals.extend(parts)
            elif line.startswith('v'):
                parts = line[1:].split()
                literals.extend(parts)
    else:
        # Plain format: just space-separated literals
        literals = content.split()

    for lit_str in literals:
        try:
            lit = int(lit_str)
            if lit == 0:
                break
            var_num = abs(lit)
            assignment[var_num] = lit > 0
        except ValueError:
            continue

    return assignment


def interpret_bitvector(literals: List, assignment: Dict[int, bool],
                        width: Optional[int], is_signed: Optional[bool]) -> str:
    """
    Interpret a bitvector variable given its literal mapping and SAT assignment.
    Returns a human-readable string representation.
    """
    bits = []

    for lit in literals:
        if lit == 'TRUE':
            bits.append(1)
        elif lit == 'FALSE':
            bits.append(0)
        elif isinstance(lit, int):
            if lit in assignment:
                bits.append(1 if assignment[lit] else 0)
            else:
                bits.append('?')  # Unknown/unassigned
        else:
            bits.append('?')

    # Check if we have any unknown bits
    if '?' in bits:
        # Return binary representation with unknowns
        return '0b' + ''.join(str(b) for b in reversed(bits))

    # Convert to integer
    # bits[0] is LSB, bits[-1] is MSB
    value = 0
    for i, bit in enumerate(bits):
        if bit:
            value |= (1 << i)

    # Handle signed interpretation
    if is_signed and width and len(bits) == width:
        # Check sign bit (MSB)
        if bits[-1]:  # Sign bit is set
            # Two's complement: value - 2^width
            value = value - (1 << width)

    # Format output
    if width:
        hex_width = (width + 3) // 4
        return f"{value} (0x{value & ((1 << width) - 1):0{hex_width}x})"
    else:
        return str(value)


def interpret_pointer(literals: List, assignment: Dict[int, bool]) -> str:
    """Interpret a pointer value."""
    bits = []
    for lit in literals:
        if lit == 'TRUE':
            bits.append(1)
        elif lit == 'FALSE':
            bits.append(0)
        elif isinstance(lit, int) and lit in assignment:
            bits.append(1 if assignment[lit] else 0)
        else:
            bits.append(0)  # Default to 0 for unknown

    value = 0
    for i, bit in enumerate(bits):
        if bit:
            value |= (1 << i)

    if value == 0:
        return "NULL (0x0)"
    else:
        return f"0x{value:x}"


def interpret_bool(literals: List, assignment: Dict[int, bool]) -> str:
    """Interpret a boolean value."""
    if not literals:
        return "unknown"

    lit = literals[0]
    if lit == 'TRUE':
        return "true"
    elif lit == 'FALSE':
        return "false"
    elif isinstance(lit, int) and lit in assignment:
        return "true" if assignment[lit] else "false"
    else:
        return "unknown"


def format_variable_name(ssa_name: str) -> Tuple[str, str]:
    """
    Parse an SSA variable name and return (simplified_name, ssa_info).

    Example: "main::1::i!0@1#2" -> ("i", "SSA#2, loop iter 1")
    """
    # Extract the base variable name
    # Format: function::scope::varname!L0@L1#L2

    parts = ssa_name.split('::')
    if len(parts) >= 3:
        func = parts[0]
        var_part = parts[-1]
    else:
        func = ""
        var_part = ssa_name

    # Parse the SSA indices
    # Format: varname!L0@L1#L2 or varname!L0@L1#L2[[index]]
    array_index = None
    if '[[' in var_part:
        match = re.match(r'(.+)\[\[(\d+)\]\]', var_part)
        if match:
            var_part = match.group(1)
            array_index = int(match.group(2))

    # Parse L0, L1, L2 indices
    match = re.match(r'([^!@#]+)(?:!(\d+))?(?:@(\d+))?(?:#(\d+))?', var_part)
    if match:
        base_name = match.group(1)
        l0 = match.group(2)  # Thread/instance
        l1 = match.group(3)  # Loop iteration
        l2 = match.group(4)  # SSA index

        ssa_info_parts = []
        if l2:
            ssa_info_parts.append(f"SSA#{l2}")
        if l1 and l1 != '1':
            ssa_info_parts.append(f"iter={l1}")
        if l0 and l0 != '0':
            ssa_info_parts.append(f"inst={l0}")

        ssa_info = ", ".join(ssa_info_parts) if ssa_info_parts else ""

        if array_index is not None:
            base_name = f"{base_name}[{array_index}]"

        if func and func != "__CPROVER":
            display_name = f"{func}::{base_name}"
        else:
            display_name = base_name

        return display_name, ssa_info

    return ssa_name, ""


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    dimacs_file = sys.argv[1]
    assignment_file = sys.argv[2]

    # Optional: filter to show only certain variables
    show_all = '--all' in sys.argv
    var_filter = None
    for arg in sys.argv[3:]:
        if arg != '--all':
            var_filter = arg
            break

    print(f"Parsing DIMACS file: {dimacs_file}")
    mappings = parse_dimacs_comments(dimacs_file)
    print(f"Found {len(mappings)} variable mappings")

    print(f"\nParsing SAT assignment: {assignment_file}")
    assignment = parse_sat_assignment(assignment_file)
    print(f"Found {len(assignment)} variable assignments")

    print("\n" + "="*70)
    print("INTERPRETED VARIABLE VALUES")
    print("="*70)

    # Group variables by their base name for cleaner output
    # and filter out internal CPROVER variables unless requested

    user_vars = {}
    cprover_vars = {}

    for ssa_name, mapping in mappings.items():
        display_name, ssa_info = format_variable_name(ssa_name)

        # Apply filter to both SSA name and display name
        if var_filter:
            if var_filter not in ssa_name and var_filter not in display_name:
                continue

        # Interpret based on type
        if mapping.type_info.startswith('signedbv') or mapping.type_info.startswith('unsignedbv'):
            value = interpret_bitvector(
                mapping.literals, assignment,
                mapping.width, mapping.is_signed
            )
        elif mapping.type_info == 'pointer':
            value = interpret_pointer(mapping.literals, assignment)
        elif mapping.type_info == 'bool':
            value = interpret_bool(mapping.literals, assignment)
        elif mapping.type_info == 'array':
            # Arrays are typically shown element-by-element
            value = f"<array of {len(mapping.literals)} bits>"
        else:
            value = f"<{mapping.type_info}>"

        entry = {
            'ssa_name': ssa_name,
            'display_name': display_name,
            'ssa_info': ssa_info,
            'value': value,
            'type': mapping.type_info
        }

        if ssa_name.startswith('__CPROVER') or ssa_name.startswith('symex::'):
            cprover_vars[ssa_name] = entry
        else:
            user_vars[ssa_name] = entry

    # Print user variables
    if user_vars:
        print("\n--- User Program Variables ---\n")

        # Sort by display name, then by SSA index
        sorted_vars = sorted(user_vars.values(),
                           key=lambda x: (x['display_name'], x['ssa_info']))

        for entry in sorted_vars:
            ssa_suffix = f"  ({entry['ssa_info']})" if entry['ssa_info'] else ""
            type_suffix = f"  [{entry['type']}]"
            print(f"{entry['display_name']:40} = {entry['value']}{ssa_suffix}{type_suffix}")

    # Print CPROVER internal variables (optional, usually less interesting)
    if cprover_vars and (var_filter or show_all):
        print("\n--- CPROVER Internal Variables ---\n")
        for ssa_name, entry in sorted(cprover_vars.items()):
            print(f"{entry['display_name']:40} = {entry['value']}  [{entry['type']}]")

    print("\n" + "="*70)


if __name__ == '__main__':
    main()
