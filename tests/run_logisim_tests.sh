#!/bin/sh
# Run every test bench in Logisim's command-line mode and compare with the
# expected tables.   Usage:  sh tests/run_logisim_tests.sh /path/to/logisim-generic-2.7.1.jar
JAR="${1:-logisim-generic-2.7.1.jar}"
cd "$(dirname "$0")" || exit 1
mkdir -p out
status=0
for t in t1_hazards t2_branch_halt t3_ram_reserved t4_timer t5_safety t6_wash_e2e; do
    java -jar "$JAR" "$t.circ" -tty table > "out/$t.txt" 2> "out/$t.err"
    if diff -q "out/$t.txt" "expected/$t.txt" > /dev/null; then
        echo "PASS  $t   (identical to expected/$t.txt)"
    else
        echo "DIFF  $t   (see: diff tests/out/$t.txt tests/expected/$t.txt)"
        status=1
    fi
done
exit $status
