// https://haslab.github.io/MFES/2122/CBMCexamples-handout.pdf
void main (void)
{
    int x;
    int y=8, z=0, w=0;
    unsigned long zz = 23;
    if (x)
        z = y - 1;
    else
        w = y + 1;
    assert (z == 7 || w == 9 && zz == 23);
}

/* // 26 file simple2.c line 2
// 26 file simple2.c line 2
// 0 file simple2.c line 4 function main
// 1 file simple2.c line 5 function main
// 2 file simple2.c line 5 function main
(9) y!0@1#2 == 8
// 3 file simple2.c line 5 function main
// 4 file simple2.c line 5 function main
(10) z!0@1#2 == 0
// 5 file simple2.c line 5 function main
// 6 file simple2.c line 5 function main
(11) w!0@1#2 == 0
// 7 file simple2.c line 6 function main
// 7 file simple2.c line 6 function main
(12) \guard#1 == !(x!0@1#1 == 0)
// 9 file simple2.c line 7 function main
(13) z!0@1#3 == 7
     guard: \guard#1
// 10 file simple2.c line 7 function main
// 12 file simple2.c line 9 function main
(14) w!0@1#3 == 9
     guard: !\guard#1
// 13 file simple2.c line 10 function main
(15) x!0@1#3 == (\guard#1 ? x!0@1#1 : 0)
// 13 file simple2.c line 10 function main
(16) z!0@1#4 == (\guard#1 ? 7 : 0)
// 13 file simple2.c line 10 function main
(17) w!0@1#4 == (\guard#1 ? 0 : 9)
// 13 file simple2.c line 10 function main
(18) ASSERT(z!0@1#4 == 7 || w!0@1#4 == 9)
// 18 file simple2.c line 11 function main
// 27  */