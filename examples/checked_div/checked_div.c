/*     pub const fn checked_div(self, rhs: u32) -> Option<Duration> {
        if rhs != 0 {
            let (secs, extra_secs) = (self.secs / (rhs as u64), self.secs % (rhs as u64));
            let (mut nanos, extra_nanos) = (self.nanos.0 / rhs, self.nanos.0 % rhs);
            nanos +=
                ((extra_secs * (NANOS_PER_SEC as u64) + extra_nanos as u64) / (rhs as u64)) as u32;
            #[cfg(not(kani))]
            debug_assert!(nanos < NANOS_PER_SEC);
            Some(Duration::new(secs, nanos))
        } else {
            None
        }
    } */

#define SIZE 20
char buffer[SIZE];

char checked_div(unsigned int lhs_second, unsigned int rhs)
{
  if(rhs != 0)
  {
  }
  return buffer[i];
  return '\0';
}

int main()
{
  int index;
  read_buffer(index);
  read_pointer(index);
}