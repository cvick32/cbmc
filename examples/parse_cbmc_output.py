from dataclasses import dataclass
import sys


class SatVariableBlock:
    def __init__(self, var_strings):
        self.vars = [SatVariable(sv) for sv in var_strings]
        self.all_false = all([var.is_false() for var in self.vars])

    def __hash__(self):
        return hash(tuple(self.vars))

    def __iter__(self):
        return self.vars

    def __repr__(self):
        if self.all_false:
            return "ALL_FALSE"
        else:
            return f"{self.vars}"


class SatVariable:
    def __init__(self, var_string: str):
        try:
            self.var = int(var_string)
        except ValueError:
            self.var = var_string

    def is_false(self):
        if isinstance(self.var, str):
            return self.var == "FALSE"
        else:
            return False

    def __repr__(self):
        return f"{self.var}"

    def __eq__(self, value):
        if isinstance(value, SatVariable) and self.var == value.var:
            return True
        else:
            return False

    def __hash__(self):
        return hash(self.var)


# // 26 file <built-in-additions> line 24
@dataclass
class GotoComment:
    number: int  # currently unknown
    type: str  # currently unknown
    source: str  # provenance of the variable
    line_number: int  # line number in the above file
    function_name: str  # containing function name


# 'guard: \guard#1'
@dataclass
class GotoGuard:
    guard_name: str


class GotoExpresion:
    expression_number: int
    expression: str
    containing_function_name: str
    guards: list[GotoGuard]
    comments: list[GotoComment]
    sat_variables: set[SatVariableBlock]

    def __init__(
        self,
        expression_number: int,
        expression: str,
        containing_function_name: str,
        guards: list[GotoGuard],
        comments: list[GotoComment],
        sat_variables: set[SatVariableBlock],
    ):
        self.expression_number = expression_number
        self.expression = expression
        self.containing_function_name = containing_function_name
        self.guards = guards
        self.comments = comments
        self.sat_variables = sat_variables
        if " == " in self.expression:
            # TODO: this is a poor heuristic for deciding what an expression 'means'
            self.lhs = self.expression.split(" == ")[0]
        else:
            self.lhs, self.rhs = None, None

    def add_guard(self, guard_line: str):
        self.guards.append(GotoGuard(guard_line.split(" ")[1]))

    def add_sat_variables(self, sat_vars: SatVariableBlock):
        if self.sat_variables is None:
            self.sat_variables = set()
        self.sat_variables.add(sat_vars)

    def get_dimacs_string(self):
        if self.containing_function_name and self.lhs:
            if self.lhs.startswith("\guard"):
                return f"goto_symex::{self.lhs}"
            return f"{self.containing_function_name}::1::{self.lhs}"
        elif self.lhs:
            return self.lhs
        return None

    def __eq__(self, name_split: list[str]):
        if self.containing_function_name:
            if name_split[0] == "goto_symex":
                return name_split[-1] in self.expression
            else:
                return (
                    name_split[0] == self.containing_function_name
                    and name_split[-1] in self.expression
                )
        else:
            return name_split[-1] in self.expression

    def __repr__(self):
        return f"({self.expression_number}) {self.expression}: {self.sat_variables}"


@dataclass
class CBMCVariable:
    name: str
    sat_variables: list[SatVariable]

    def __repr__(self):
        return f"CBMCVariable({self.name}): {self.sat_variables}"


def parse_dimacs(lines, expressions: dict[str, GotoExpresion]) -> list[CBMCVariable]:
    loose_cbmc_vars = []
    for i, comment_line in enumerate(lines):
        print(f"Dimacs comment {i}")
        comment_line = comment_line.strip()
        splits = comment_line.split(" ")
        name, sat_variables = splits[1], SatVariableBlock(splits[2:])
        if name in expressions:
            expressions[name].add_sat_variables(sat_variables)
        else:
            new_cbmc_variable = CBMCVariable(name, sat_variables)
            loose_cbmc_vars.append(new_cbmc_variable)
    return loose_cbmc_vars


def parse_goto(lines) -> dict[str, GotoExpresion]:
    dimacs_to_expression = {}
    phase = "header"
    last_expression_added = None
    cur_comments: list[GotoComment] = []
    for line in lines:
        line = line.strip()

        if line.startswith("//"):
            split = line.split(" ")
            if len(split) < 3:
                number = int(split[1])
                file, source, line_number, function_name = None, None, None, None
            elif len(split) == 6:
                number, file, source, line_number, function_name = (
                    int(split[1]),
                    split[2],
                    split[3],
                    int(split[5]),
                    None,
                )
            elif len(split) == 8:
                if split[6] != "function":
                    raise ValueError(f"Have not implemented {split[6]} names in {line}")
                number, file, source, line_number, function_name = (
                    int(split[1]),
                    split[2],
                    split[3],
                    int(split[5]),
                    split[7],
                )
            else:
                raise ValueError(f"Unknown Comment type: {line}")
            cur_comments.append(
                GotoComment(number, file, source, line_number, function_name)
            )

        elif line.startswith("("):
            phase = "expression"
            first_space = line.index(" ")
            expression = line[first_space:].strip()
            try:
                expression_number = int(line[:first_space].strip("()"))
            except ValueError:
                if "sliced" in line[:first_space]:
                    # sliced expressions are not produced in dimacs
                    expression_number = -1
            containing_function_name = None
            for comment in cur_comments:
                if comment.function_name is not None:
                    containing_function_name = comment.function_name
                    break
            expr = GotoExpresion(
                expression_number,
                expression,
                containing_function_name,
                [],
                cur_comments,
                set(),
            )
            dimacs_string = expr.get_dimacs_string()
            print(f"{expr}: {dimacs_string}")
            if dimacs_string is not None:
                last_expression_added = dimacs_string
                dimacs_to_expression[dimacs_string] = expr
            cur_comments = []
        else:
            if phase == "header":
                continue
            elif phase == "expression":
                # Lists guards underneath the GotoExpresion. We know that this
                # is the most recent variable we added, so we just add the guard
                # to the last variable.
                last_expression = dimacs_to_expression[last_expression_added]
                if line.startswith("guard:"):
                    last_expression.add_guard(line)
                else:
                    ValueError(f"Unknown addendum to goto variable: {line}")

            else:
                raise ValueError(f"Invalid input: {line}")
    return dimacs_to_expression


# Example usage:
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 parse_cbmc_output.py <goto-file> <dimacs-file>")
        sys.exit(1)

    goto_file, dimacs_file = sys.argv[1], sys.argv[2]

    try:
        with open(goto_file, "r") as gf:
            goto_lines = gf.readlines()
            index = goto_lines.index("Program constraints:\n")
            goto_lines = goto_lines[index + 1 :]
    except FileNotFoundError:
        print(f"GOTO file not found: {goto_file}")
    try:
        with open(dimacs_file, "r") as df:
            dimacs_lines = [
                comment_line
                for comment_line in df.readlines()
                if comment_line.startswith("c")
            ]
    except FileNotFoundError:
        print(f"DIMACS file not found: {dimacs_file}")

    goto_expressions = parse_goto(goto_lines)
    parsed_dimacs = parse_dimacs(dimacs_lines, goto_expressions)
    final_expressions = list(goto_expressions.values())

    breakpoint()
