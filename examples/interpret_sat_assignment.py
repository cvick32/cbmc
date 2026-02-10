#!/usr/bin/env python3
"""
Interpret a SAT solver's satisfying assignment in terms of the original
C program variables using CBMC's DIMACS mapping comments.

Supports multiple SAT solver output formats:
  - Kissat: Uses 's SATISFIABLE' and 'v' prefixed assignment lines
  - CaDiCaL: Same format as Kissat
  - MiniSat/Glucose: Uses 'SAT' line followed by literals (no 'v' prefix)
  - Plain: Space-separated literals ending with 0

Usage:
    python interpret_sat_assignment.py <dimacs_file> <assignment_file> [options]

Options:
    --solver {auto,kissat,cadical,minisat,glucose,plain}
                        SAT solver format (default: auto-detect)
    --all               Show CPROVER internal variables
    --filter PATTERN    Only show variables matching pattern
    --show-cnf-vars     Show CNF variable numbers for each decoded variable
    --coverage          Show summary of CNF variable coverage
    --unmapped          List all unmapped CNF variable numbers
    --var-table         Output CSV lookup table: CNF_var -> program_var (for activity score correlation)

Examples:
    # Auto-detect solver format
    python interpret_sat_assignment.py program.cnf sat_output.txt

    # Specify Kissat format
    python interpret_sat_assignment.py program.cnf sat_output.txt --solver kissat

    # Filter to only show variable 'x'
    python interpret_sat_assignment.py program.cnf sat_output.txt --filter x
"""

import sys
import re
import argparse
from abc import ABC, abstractmethod
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


@dataclass
class TseitinMapping:
    """Mapping for a Tseitin auxiliary variable."""
    var_no: int           # The DIMACS variable number
    gate_type: str        # AND, OR, XOR, ITE
    inputs: List[int]     # Input literals (signed, negative means negated)


# =============================================================================
# SAT Solver Output Parsers
# =============================================================================

class SolverParser(ABC):
    """Abstract base class for SAT solver output parsers."""

    name: str = "unknown"

    @abstractmethod
    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        """
        Parse solver output and return (status, assignment).

        Returns:
            status: "SATISFIABLE", "UNSATISFIABLE", or None if unknown
            assignment: Dict mapping variable number to True/False
        """
        pass

    @staticmethod
    def _parse_literals(literals: List[str]) -> Dict[int, bool]:
        """Parse a list of literal strings into an assignment dict."""
        assignment = {}
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


class KissatParser(SolverParser):
    """
    Parser for Kissat SAT solver output.

    Format:
        c <comments>
        s SATISFIABLE
        v 1 -2 3 4 ...
        v 5 6 -7 ...
        v 0
    """

    name = "kissat"

    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        status = None
        literals = []

        for line in content.split('\n'):
            line = line.strip()

            # Parse status line
            if line.startswith('s '):
                status = line[2:].strip()

            # Parse value lines
            elif line.startswith('v '):
                parts = line[2:].split()
                literals.extend(parts)
            elif line.startswith('v'):
                parts = line[1:].split()
                literals.extend(parts)

        assignment = self._parse_literals(literals)
        return status, assignment


class CadicalParser(SolverParser):
    """
    Parser for CaDiCaL SAT solver output.

    Format is identical to Kissat:
        c <comments>
        s SATISFIABLE
        v 1 -2 3 4 ...
        v 0
    """

    name = "cadical"

    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        # CaDiCaL uses the same format as Kissat
        return KissatParser().parse(content)


class MinisatParser(SolverParser):
    """
    Parser for MiniSat/Glucose SAT solver output.

    Format:
        SAT
        1 -2 3 4 -5 6 ... 0

    Or for UNSAT:
        UNSAT
    """

    name = "minisat"

    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        status = None
        literals = []
        found_status = False

        for line in content.split('\n'):
            line = line.strip()

            if not line:
                continue

            # Parse status line
            if line == 'SAT':
                status = 'SATISFIABLE'
                found_status = True
            elif line == 'UNSAT':
                status = 'UNSATISFIABLE'
                found_status = True
            elif found_status and status == 'SATISFIABLE':
                # After SAT line, remaining lines are literals
                parts = line.split()
                literals.extend(parts)

        assignment = self._parse_literals(literals)
        return status, assignment


class GlucoseParser(SolverParser):
    """
    Parser for Glucose SAT solver output.

    Same format as MiniSat.
    """

    name = "glucose"

    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        return MinisatParser().parse(content)


class PlainParser(SolverParser):
    """
    Parser for plain DIMACS assignment format.

    Format:
        1 -2 3 4 -5 6 ... 0

    Or with 'v' prefix (extracted from solver output):
        v 1 -2 3 4 -5 6 ...
        v 0
    """

    name = "plain"

    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        literals = []

        # Check if it uses 'v' prefix format
        if 'v ' in content or content.lstrip().startswith('v'):
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('v '):
                    parts = line[2:].split()
                    literals.extend(parts)
                elif line.startswith('v'):
                    parts = line[1:].split()
                    literals.extend(parts)
        else:
            # Plain space-separated format
            literals = content.split()

        assignment = self._parse_literals(literals)
        # Plain format doesn't include status
        return 'SATISFIABLE' if assignment else None, assignment


class AutoParser(SolverParser):
    """
    Auto-detecting parser that tries to identify the solver format.
    """

    name = "auto"

    def parse(self, content: str) -> Tuple[Optional[str], Dict[int, bool]]:
        solver, confidence = self.detect_solver(content)
        parser = get_parser(solver)
        return parser.parse(content)

    @staticmethod
    def detect_solver(content: str) -> Tuple[str, str]:
        """
        Detect which SAT solver produced the output.

        Returns:
            (solver_name, confidence) where confidence is 'high', 'medium', or 'low'
        """
        # Check for Kissat signature
        if 'Kissat SAT Solver' in content:
            return 'kissat', 'high'

        # Check for CaDiCaL signature
        if 'CaDiCaL' in content or 'cadical' in content.lower():
            return 'cadical', 'high'

        # Check for Glucose signature
        if 'Glucose' in content or 'glucose' in content.lower():
            return 'glucose', 'high'

        # Check for MiniSat signature
        if 'MiniSat' in content or 'minisat' in content.lower():
            return 'minisat', 'high'

        # Check for 's SATISFIABLE' format (Kissat/CaDiCaL style)
        if re.search(r'^s\s+(SATISFIABLE|UNSATISFIABLE)', content, re.MULTILINE):
            # Has 'v' lines -> Kissat/CaDiCaL format
            if re.search(r'^v\s+', content, re.MULTILINE):
                return 'kissat', 'medium'

        # Check for 'SAT'/'UNSAT' format (MiniSat/Glucose style)
        if re.search(r'^SAT\s*$', content, re.MULTILINE):
            return 'minisat', 'medium'
        if re.search(r'^UNSAT\s*$', content, re.MULTILINE):
            return 'minisat', 'medium'

        # Check for 'v' lines without 's' line
        if re.search(r'^v\s+', content, re.MULTILINE):
            return 'plain', 'medium'

        # Fall back to plain format
        return 'plain', 'low'


# Parser registry
PARSERS = {
    'kissat': KissatParser,
    'cadical': CadicalParser,
    'minisat': MinisatParser,
    'glucose': GlucoseParser,
    'plain': PlainParser,
    'auto': AutoParser,
}


def get_parser(solver: str) -> SolverParser:
    """Get a parser instance for the specified solver."""
    if solver not in PARSERS:
        raise ValueError(f"Unknown solver: {solver}. Available: {list(PARSERS.keys())}")
    return PARSERS[solver]()


def parse_type_info(type_str: str) -> Tuple[Optional[int], Optional[bool]]:
    """Parse type string to extract width and signedness."""
    # Match patterns like "signedbv[32]", "unsignedbv[64]"
    match = re.match(r'(signed|unsigned)bv\[(\d+)\]', type_str)
    if match:
        is_signed = match.group(1) == 'signed'
        width = int(match.group(2))
        return width, is_signed
    return None, None


@dataclass
class DimacsParseResult:
    """Result from parsing DIMACS file."""
    mappings: Dict[str, VariableMapping]
    tseitin_mappings: Dict[int, TseitinMapping]  # var_no -> TseitinMapping
    total_vars: int
    total_clauses: int
    mapped_cnf_vars: set  # Set of CNF variable numbers that are mapped


def parse_dimacs_comments(dimacs_file: str) -> DimacsParseResult:
    """Parse DIMACS file and extract variable mappings from comments."""
    mappings = {}
    tseitin_mappings = {}
    mapped_cnf_vars = set()
    total_vars = 0
    total_clauses = 0

    with open(dimacs_file, 'r') as f:
        for line in f:
            # Parse problem line
            if line.startswith('p cnf'):
                parts = line.split()
                if len(parts) >= 4:
                    total_vars = int(parts[2])
                    total_clauses = int(parts[3])
                continue

            if not line.startswith('c '):
                continue

            # Remove the 'c ' prefix
            content = line[2:].strip()
            if not content:
                continue

            # Check for @tseitin comments
            if content.startswith('@tseitin '):
                parts = content.split()
                # Format: @tseitin <var_no> <gate_type> <input1> <input2> ...
                if len(parts) >= 4:
                    try:
                        var_no = int(parts[1])
                        gate_type = parts[2]
                        inputs = [int(x) for x in parts[3:]]
                        tseitin_mappings[var_no] = TseitinMapping(
                            var_no=var_no,
                            gate_type=gate_type,
                            inputs=inputs
                        )
                        mapped_cnf_vars.add(var_no)
                    except ValueError:
                        pass
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
                        var_num = abs(lit)
                        literals.append(var_num)  # Store the variable number
                        mapped_cnf_vars.add(var_num)
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

    return DimacsParseResult(
        mappings=mappings,
        tseitin_mappings=tseitin_mappings,
        total_vars=total_vars,
        total_clauses=total_clauses,
        mapped_cnf_vars=mapped_cnf_vars
    )


@dataclass
class ParseResult:
    """Result from parsing SAT solver output."""
    status: Optional[str]
    assignment: Dict[int, bool]
    detected_solver: Optional[str] = None
    detection_confidence: Optional[str] = None


def parse_sat_assignment(assignment_file: str, solver: str = 'auto') -> ParseResult:
    """
    Parse SAT solver output to get variable assignments.

    Args:
        assignment_file: Path to the solver output file
        solver: Solver format ('auto', 'kissat', 'cadical', 'minisat', 'glucose', 'plain')

    Returns:
        ParseResult with status, assignment, and optional detection info
    """
    with open(assignment_file, 'r') as f:
        content = f.read()

    detected_solver = None
    detection_confidence = None

    # For auto-detection, detect the solver format
    if solver == 'auto':
        detected_solver, detection_confidence = AutoParser.detect_solver(content)

    parser = get_parser(solver)
    status, assignment = parser.parse(content)

    return ParseResult(
        status=status,
        assignment=assignment,
        detected_solver=detected_solver,
        detection_confidence=detection_confidence
    )


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


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description='Interpret SAT solver assignments using CBMC variable mappings.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported solver formats:
  kissat   - Kissat SAT Solver (s/v line format)
  cadical  - CaDiCaL SAT Solver (s/v line format)
  minisat  - MiniSat SAT Solver (SAT/UNSAT + literals)
  glucose  - Glucose SAT Solver (same as minisat)
  plain    - Plain DIMACS assignment format
  auto     - Auto-detect based on file content (default)

Examples:
  %(prog)s program.cnf sat_output.txt
  %(prog)s program.cnf sat_output.txt --solver kissat
  %(prog)s program.cnf sat_output.txt --filter main::x
  %(prog)s program.cnf sat_output.txt --all
        """
    )

    parser.add_argument(
        'dimacs_file',
        help='DIMACS CNF file with CBMC variable mapping comments'
    )

    parser.add_argument(
        'assignment_file',
        help='SAT solver output file with variable assignment'
    )

    parser.add_argument(
        '--solver', '-s',
        choices=['auto', 'kissat', 'cadical', 'minisat', 'glucose', 'plain'],
        default='auto',
        help='SAT solver output format (default: auto-detect)'
    )

    parser.add_argument(
        '--all', '-a',
        action='store_true',
        dest='show_all',
        help='Show CPROVER internal variables'
    )

    parser.add_argument(
        '--filter', '-f',
        dest='var_filter',
        metavar='PATTERN',
        help='Only show variables matching this pattern'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress informational messages'
    )

    parser.add_argument(
        '--show-cnf-vars', '-v',
        action='store_true',
        dest='show_cnf_vars',
        help='Show CNF variable numbers for each decoded variable'
    )

    parser.add_argument(
        '--coverage', '-c',
        action='store_true',
        help='Show summary of CNF variable coverage'
    )

    parser.add_argument(
        '--unmapped', '-u',
        action='store_true',
        help='List all unmapped CNF variable numbers'
    )

    parser.add_argument(
        '--var-table', '-t',
        action='store_true',
        dest='var_table',
        help='Output CSV lookup table: CNF_var -> program_var (for activity score correlation)'
    )

    return parser


def format_cnf_vars(literals: List) -> str:
    """Format CNF variable numbers for display."""
    # Extract only numeric literals (skip TRUE/FALSE)
    numeric_lits = [lit for lit in literals if isinstance(lit, int)]
    if not numeric_lits:
        return "(all constant)"

    # Check if they're consecutive
    if len(numeric_lits) > 1:
        min_lit = min(numeric_lits)
        max_lit = max(numeric_lits)
        if max_lit - min_lit + 1 == len(numeric_lits):
            # Consecutive range
            return f"[{min_lit}..{max_lit}]"

    # Not consecutive or just one, list them
    if len(numeric_lits) <= 8:
        return f"[{', '.join(str(l) for l in numeric_lits)}]"
    else:
        # Too many, show range summary
        return f"[{numeric_lits[0]}..{numeric_lits[-1]}] ({len(numeric_lits)} vars)"


def main():
    parser = create_argument_parser()
    args = parser.parse_args()

    dimacs_file = args.dimacs_file
    assignment_file = args.assignment_file
    solver = args.solver
    show_all = args.show_all
    var_filter = args.var_filter
    quiet = args.quiet
    show_cnf_vars = args.show_cnf_vars
    show_coverage = args.coverage
    show_unmapped = args.unmapped
    var_table = args.var_table

    if not quiet:
        print(f"Parsing DIMACS file: {dimacs_file}")
    dimacs_result = parse_dimacs_comments(dimacs_file)
    mappings = dimacs_result.mappings
    if not quiet:
        print(f"Found {len(mappings)} variable mappings")

    if not quiet:
        print(f"\nParsing SAT assignment: {assignment_file}")
    result = parse_sat_assignment(assignment_file, solver)
    assignment = result.assignment
    if not quiet:
        if result.detected_solver:
            print(f"Auto-detected solver format: {result.detected_solver} (confidence: {result.detection_confidence})")
        print(f"Found {len(assignment)} variable assignments")
        if result.status:
            print(f"Solver status: {result.status}")

    # Show coverage summary if requested
    if show_coverage or show_unmapped:
        print("\n" + "="*70)
        print("CNF VARIABLE COVERAGE")
        print("="*70)

        all_cnf_vars = set(range(1, dimacs_result.total_vars + 1))
        unmapped_vars = all_cnf_vars - dimacs_result.mapped_cnf_vars
        num_tseitin = len(dimacs_result.tseitin_mappings)
        num_program_vars = len(dimacs_result.mapped_cnf_vars) - num_tseitin

        print(f"\nTotal CNF variables:    {dimacs_result.total_vars}")
        print(f"Total CNF clauses:      {dimacs_result.total_clauses}")
        print(f"Mapped program vars:    {num_program_vars}")
        print(f"Mapped Tseitin vars:    {num_tseitin}")
        print(f"Total mapped vars:      {len(dimacs_result.mapped_cnf_vars)}")
        print(f"Unmapped CNF variables: {len(unmapped_vars)}")

        coverage_pct = 100.0 * len(dimacs_result.mapped_cnf_vars) / dimacs_result.total_vars if dimacs_result.total_vars > 0 else 0
        print(f"Coverage:               {coverage_pct:.1f}%")

        if show_unmapped and unmapped_vars:
            print(f"\nUnmapped variable numbers:")
            # Group consecutive numbers for cleaner display
            sorted_unmapped = sorted(unmapped_vars)
            ranges = []
            start = sorted_unmapped[0]
            end = start
            for v in sorted_unmapped[1:]:
                if v == end + 1:
                    end = v
                else:
                    ranges.append((start, end))
                    start = v
                    end = v
            ranges.append((start, end))

            for start, end in ranges:
                if start == end:
                    print(f"  {start}")
                else:
                    print(f"  {start}-{end} ({end - start + 1} vars)")

            print(f"\nNote: Unmapped variables may include internal CBMC variables")
            print(f"      that are not tracked by Tseitin metadata.")

    # Output var-table (CSV lookup table) if requested
    if var_table:
        print("\n" + "="*70)
        print("CNF VARIABLE LOOKUP TABLE (CSV)")
        print("="*70)
        print("\ncnf_var,bit_index,program_var,type,gate_inputs")

        # Build lookup: cnf_var -> (program_var, bit_index, type, gate_inputs)
        cnf_to_var = {}
        for ssa_name, mapping in mappings.items():
            display_name, ssa_info = format_variable_name(ssa_name)
            full_name = f"{display_name}#{ssa_info.replace('SSA#', '')}" if 'SSA#' in ssa_info else display_name

            for bit_idx, lit in enumerate(mapping.literals):
                if isinstance(lit, int):
                    cnf_to_var[lit] = (full_name, bit_idx, mapping.type_info, "")

        # Add Tseitin mappings
        tseitin_mappings = dimacs_result.tseitin_mappings
        for var_no, tseitin in tseitin_mappings.items():
            inputs_str = " ".join(str(x) for x in tseitin.inputs)
            cnf_to_var[var_no] = (f"<{tseitin.gate_type}>", -1, "tseitin", inputs_str)

        # Output sorted by CNF variable number
        for cnf_var in sorted(cnf_to_var.keys()):
            prog_var, bit_idx, var_type, gate_inputs = cnf_to_var[cnf_var]
            print(f"{cnf_var},{bit_idx},{prog_var},{var_type},{gate_inputs}")

        # Also list any remaining unmapped variables (should be none if tracking is complete)
        all_cnf_vars = set(range(1, dimacs_result.total_vars + 1))
        unmapped = sorted(all_cnf_vars - set(cnf_to_var.keys()))
        for cnf_var in unmapped:
            print(f"{cnf_var},-1,<unknown>,unmapped,")

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
            'type': mapping.type_info,
            'literals': mapping.literals,  # Store for --show-cnf-vars
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
            line = f"{entry['display_name']:40} = {entry['value']}{ssa_suffix}{type_suffix}"
            print(line)
            if show_cnf_vars:
                cnf_str = format_cnf_vars(entry['literals'])
                print(f"{'':40}   CNF vars: {cnf_str}")

    # Print CPROVER internal variables (optional, usually less interesting)
    if cprover_vars and (var_filter or show_all):
        print("\n--- CPROVER Internal Variables ---\n")
        for ssa_name, entry in sorted(cprover_vars.items()):
            line = f"{entry['display_name']:40} = {entry['value']}  [{entry['type']}]"
            print(line)
            if show_cnf_vars:
                cnf_str = format_cnf_vars(entry['literals'])
                print(f"{'':40}   CNF vars: {cnf_str}")

    print("\n" + "="*70)


if __name__ == '__main__':
    main()
