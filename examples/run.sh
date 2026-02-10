
cbmc-instrument $1 --dimacs --outfile program.cnf

$2 program.cnf > sat_output.txt

python3 interpret_sat_assignment.py program.cnf sat_output.txt --var-table

