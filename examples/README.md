# SSA-to-DIMACS Mapping Instrumentation

This document describes modifications to CBMC and scripts for mapping between C program variables and DIMACS CNF encodings.

## 1. Changes Made to CBMC

### Phase 1: Enable Debug Logging

#### `src/solvers/flattening/boolbv_map.cpp`
- Added `#include <goto-symex/ssa_step_tracker.h>`
- Removed `#ifdef DEBUG` conditional around logging
- Changed output from `std::cout` to `std::cerr`
- Added SSA step index to output

**Output format:**
```
NEW: @step=13 main::1::i!0@1#1:0=1
```
Meaning: At SSA step 13, variable `main::1::i!0@1#1`, bit 0, maps to DIMACS literal 1.

#### `src/solvers/prop/prop_conv_solver.cpp`
- Added includes for `ssa_step_tracker.h` and `iostream`
- Changed `#if 0` to `#if 1` to enable expression-to-literal cache logging
- Added step index to output

**Output format:**
```
@step=13 true==<expression tree>
```

### Phase 2: Enhanced DIMACS Comments

#### `src/solvers/flattening/bv_dimacs.cpp`
- Added `#include <util/bitvector_types.h>`
- Added type information suffix to DIMACS comment lines

**Before:**
```
c main::1::i!0@1#1 1 2 3 4 ... 32
```

**After:**
```
c main::1::i!0@1#1 1 2 3 4 ... 32 @type=signedbv[32]
```

Supported types: `signedbv[N]`, `unsignedbv[N]`, `pointer`, `array`, `bool`

### Phase 3: SSA Step Index Tracking

#### `src/goto-symex/ssa_step_tracker.h` (NEW FILE)
Header-only tracker with inline static variables:
```cpp
struct ssa_step_trackert {
    static inline std::size_t current_step_index = 0;
    static inline bool active = false;
};
```

#### `src/goto-symex/symex_target_equation.cpp`
Sets `ssa_step_trackert::current_step_index` before all `decision_procedure` calls in:
- `convert_assignments`
- `convert_decls`
- `convert_guards`
- `convert_assumptions`
- `convert_goto_instructions`
- `convert_constraints`
- `convert_assertions`
- `convert_function_calls`
- `convert_io`

---

## 2. Scripts

### `examples/interpret_sat_assignment.py`

Translates SAT solver assignments back to C program variable values.

**Features:**
- Parses DIMACS comments with `@type=` annotations
- Interprets signed/unsigned bitvectors of any width
- Handles pointers, booleans, and arrays
- Shows SSA version numbers (SSA#1, SSA#2, etc.)
- Filters by variable name
- Optionally shows CPROVER internal variables

**How it works:**
1. Parses DIMACS file comment lines (`c variable literals... @type=T`)
2. Builds mapping: variable name → list of DIMACS literal numbers
3. Parses SAT assignment (positive literal = true, negative = false)
4. For each variable, collects bit values and reconstructs the integer
5. Applies two's complement for signed types
6. Formats output with hex values and SSA info

---

## 3. How to Run

### Build CBMC with Instrumentation

```bash
cd /Users/cvick-admin/Documents/research/cbmc

# Configure
cmake -S . -Bbuild -DCMAKE_BUILD_TYPE=Debug -DWITH_JBMC=OFF

# Build
cmake --build build -j$(sysctl -n hw.ncpu)
```

### Generate DIMACS with Mappings

```bash
# Generate DIMACS file (mappings in comments, debug to stderr)
./build/bin/cbmc program.c --dimacs --outfile program.cnf 2> debug.log
```

### Solve with SAT Solver

```bash
# Using kissat (or minisat, cadical, etc.)
kissat program.cnf > sat_output.txt

# Check result
grep "^s " sat_output.txt
# s SATISFIABLE = counterexample found
# s UNSATISFIABLE = property holds
```

### Interpret SAT Assignment

```bash
# Extract assignment lines
grep "^v " sat_output.txt > assignment.txt

# Interpret all user variables
python3 examples/interpret_sat_assignment.py program.cnf assignment.txt

# Filter to specific variable
python3 examples/interpret_sat_assignment.py program.cnf assignment.txt "main::x"

# Show CPROVER internal variables too
python3 examples/interpret_sat_assignment.py program.cnf assignment.txt --all
```

### Complete Example

```bash
cd /Users/cvick-admin/Documents/research/cbmc/examples/sat_demo

# 1. Generate DIMACS
../../build/bin/cbmc simple_sat.c --dimacs --outfile simple_sat.cnf 2>/dev/null

# 2. Solve
kissat simple_sat.cnf > sat_output.txt

# 3. Interpret
grep "^v " sat_output.txt > assignment.txt
python3 ../interpret_sat_assignment.py simple_sat.cnf assignment.txt
```

**Example output:**
```
======================================================================
INTERPRETED VARIABLE VALUES
======================================================================

--- User Program Variables ---

main::x                                  = 10 (0x0000000a)  (SSA#1)  [signedbv[32]]
main::y                                  = 5 (0x00000005)  (SSA#1)  [signedbv[32]]
```

### Examine Debug Logs

```bash
# View bitvector-to-literal mappings
grep "^NEW:" debug.log | head -20

# View expression-to-literal cache
grep "^@step=" debug.log | head -20

# View DIMACS variable comments
grep "^c " program.cnf | head -20
```

---

## File Locations

| File | Description |
|------|-------------|
| `src/solvers/flattening/boolbv_map.cpp` | Bitvector mapping logging |
| `src/solvers/prop/prop_conv_solver.cpp` | Expression cache logging |
| `src/solvers/flattening/bv_dimacs.cpp` | DIMACS comment enhancement |
| `src/goto-symex/ssa_step_tracker.h` | Step index tracker (new) |
| `src/goto-symex/symex_target_equation.cpp` | Step index setting |
| `examples/interpret_sat_assignment.py` | SAT assignment interpreter |
| `examples/sat_demo/simple_sat.c` | Simple test program |
| `examples/sat_demo/progress.md` | This documentation |

---

## 4. Tseitin Variable Tracking

### Background

During CNF conversion, CBMC creates auxiliary "Tseitin" variables to encode boolean gates (AND, OR, XOR, ITE). Previously, these variables appeared in the DIMACS output without any semantic labels, making it difficult to correlate SAT solver activity scores with program semantics.

### Changes Made

#### `src/solvers/sat/cnf.h`

Added Tseitin tracking infrastructure to the `cnft` class:

```cpp
// Gate type enumeration
enum class gate_typet { AND, OR, XOR, ITE };

// Metadata for each Tseitin variable
struct tseitin_entryt {
  gate_typet gate_type;
  std::vector<literalt> inputs;  // 2 inputs for AND/OR/XOR, 3 for ITE
};

// Map from output literal to gate metadata
using tseitin_mapt = std::map<literalt, tseitin_entryt>;
const tseitin_mapt& get_tseitin_map() const { return tseitin_map; }

protected:
  tseitin_mapt tseitin_map;
```

#### `src/solvers/sat/cnf.cpp`

Modified gate functions to record Tseitin metadata:

- `land(literalt a, literalt b)` - records AND gate with 2 inputs
- `land(const bvt &bv)` - records AND gate with N inputs
- `lor(literalt a, literalt b)` - records OR gate with 2 inputs
- `lor(const bvt &bv)` - records OR gate with N inputs
- `lxor(literalt a, literalt b)` - records XOR gate with 2 inputs
- `lselect(literalt a, literalt b, literalt c)` - records ITE gate with 3 inputs

Example addition to `land()`:
```cpp
literalt o = new_variable();
gate_and(a, b, o);
tseitin_map[o] = {gate_typet::AND, {a, b}};  // NEW
return o;
```

#### `src/solvers/flattening/bv_dimacs.cpp`

Added output of `@tseitin` comments after program variable mappings:

```cpp
// Dump Tseitin variable mappings
for(const auto &entry : dimacs_cnf_prop.get_tseitin_map())
{
  out << "c @tseitin " << lit.var_no();
  switch(tseitin.gate_type) {
    case cnft::gate_typet::AND: out << " AND"; break;
    case cnft::gate_typet::OR:  out << " OR"; break;
    case cnft::gate_typet::XOR: out << " XOR"; break;
    case cnft::gate_typet::ITE: out << " ITE"; break;
  }
  for(const auto &input : tseitin.inputs)
    out << " " << input.dimacs();
  out << "\n";
}
```

### DIMACS Output Format

```
c @tseitin 513 AND 1 2           # var 513 = AND(var 1, var 2)
c @tseitin 514 OR 513 3          # var 514 = OR(var 513, var 3)
c @tseitin 515 XOR 10 11         # var 515 = XOR(var 10, var 11)
c @tseitin 516 ITE 5 6 7         # var 516 = IF var5 THEN var6 ELSE var7
c @tseitin 517 AND -1 -2 -3 -4   # var 517 = AND(NOT 1, NOT 2, NOT 3, NOT 4)
```

Input literals use DIMACS sign convention: negative means negated.

### Script Updates

#### `examples/interpret_sat_assignment.py`

Added parsing for `@tseitin` comments:

```python
@dataclass
class TseitinMapping:
    var_no: int           # The DIMACS variable number
    gate_type: str        # AND, OR, XOR, ITE
    inputs: List[int]     # Input literals (signed, negative means negated)
```

New/updated command-line options:

- `--coverage` - Now shows separate counts for program vars vs Tseitin vars
- `--var-table` - CSV now includes gate type and inputs for Tseitin vars

**Example coverage output:**
```
Total CNF variables:    579
Total CNF clauses:      69
Mapped program vars:    545
Mapped Tseitin vars:    2
Total mapped vars:      547
Unmapped CNF variables: 32
Coverage:               94.5%
```

**Example var-table CSV output:**
```
cnf_var,bit_index,program_var,type,gate_inputs
1,0,main::i#1,signedbv[32],
...
577,-1,<XOR>,tseitin,544 545
578,-1,<AND>,tseitin,-546 -547 -548 ...
```

### Usage

```bash
# Generate DIMACS with Tseitin tracking
./build/bin/cbmc program.c --dimacs --outfile program.cnf

# Check Tseitin comments
grep '@tseitin' program.cnf

# View coverage including Tseitin vars
python3 examples/interpret_sat_assignment.py program.cnf sat_output.txt --coverage

# Generate CSV lookup table with Tseitin entries
python3 examples/interpret_sat_assignment.py program.cnf sat_output.txt --var-table
```

### Limitations

Not all auxiliary variables are tracked. Variables created through:
- Direct clause generation (bypassing `land`/`lor`/`lxor`/`lselect`)
- Lower-level encoding functions
- Comparison and arithmetic operations

These will appear as "unmapped" in coverage reports. The current implementation tracks the high-level boolean gate operations which account for most Tseitin variables in typical verification tasks.
