// array_sum.c — nondet array summed in a loop CBMC unrolls fully.
// Each iteration produces a fresh SSA accumulator (sum#1..sum#N) and array
// element, so the CBMC view shows per-depth variables with their own activity.

#define N 20

int nondet_int(void);

int main(void)
{
  int a[N];
  int i;
  int sum = 0;

  for (i = 0; i < N; i++)
  {
    int v = nondet_int();
    __CPROVER_assume(v >= 0 && v <= 7);   // 3 bits per element
    a[i] = v;
    sum = sum + a[i];
  }

  // 0..140 reachable (N*7=140); 117 needs some combination to refute.
  __CPROVER_assert(sum != 117, "sum cannot be 117");
  return 0;
}
