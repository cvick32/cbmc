// Simple program to demonstrate SAT assignment interpretation
// This creates a satisfiable formula where we can see the variable values

int main() {
    int x;
    int y;

    // Constrain x and y to specific ranges
    __CPROVER_assume(x >= 0 && x <= 10);
    __CPROVER_assume(y >= 0 && y <= 10);

    // This assertion will fail when x + y == 15
    // So the SAT solver will find values where x + y == 15
    __CPROVER_assert(x + y != 15, "sum should not be 15");

    return 0;
}
