# ELL782

## Assignment 2 - Washing Machine
Five-Stage Pipelined Microcontroller

------
2024EEN2016 - Humanshu D G
------

1. LOGISIM VERSION
------------------
* washing_pipeline.circ is a Logisim 2.7.1 project file.
* Logisim-Evolution opens 2.7.x files and converts them on load. Save the converted copy under a
  new name, and repeat the quick check of section 5 after conversion.
* Java 8 or newer is required.
* Built-in components used: Pin, Tunnel, Splitter, Constant, Clock, AND/OR/NOR/XOR/NOT gates, Register,
  ROM, RAM, Text. The Plexers and Arithmetic libraries are not loaded at all. Every multiplexer, decoder,
  comparator, adder, incrementer, the ALU and the timer incrementer are gate-level sub-circuits.

2. FILES
--------
  washing_pipeline.circ      complete design; main = interactive top level, 22 named sub-circuits
  program.asm / program.hex  washing program (source / Logisim "v2.0 raw" ROM image, already in the ROM)
  program_listing.txt        address / hex / assembly table (plain text; LaTeX version: latex/listing.tex)
  latex/                     LaTeX sources of the PDF deliverables (run "make" in latex/ to build them):
       isa.tex  architecture.tex  memory_map.tex  listing.tex  pipeline_traces.tex  validation.tex
       common.tex (shared preamble), generated/ (tables produced from the simulation runs)
  tests/tN_*.circ            six self-running test benches (same sub-circuits, scripted inputs, plant model)
  tests/tN_*.asm / .hex      their programs (t6 uses program.asm)
  tests/expected/*.txt       expected "logisim -tty table" output of every test bench
  tests/run_logisim_tests.sh runs all benches in Logisim and diffs against tests/expected
  RUNNING_IN_LOGISIM.md      detailed step-by-step instructions (GUI and command line)
  tools/                     optional helpers: asm.py (assembler), isa_ref.py (ISA reference model),
                             design.py + logisim_gen.py (regenerate the .circ files),
                             circsim.py (netlist checker / simulator), make_reports.py (re-run checks
                             and regenerate latex/generated + tests/expected)

3. LOAD / RUN PROCEDURE (short version - see RUNNING_IN_LOGISIM.md for details)
-------------------------------------------------------------------------------
  1. java -jar logisim-generic-2.7.1.jar washing_pipeline.circ      (or File > Open)
  2. Select the Poke tool (hand icon).
  3. Reset: poke RESET to 1, then back to 0. Simulate > Reset Simulation (Ctrl+R) also returns
     everything to the reset state.
  4. Clock: the CLK component is the single global clock. Simulate > Tick Once (Ctrl+T) toggles it
     (2 ticks = 1 CPU cycle). Simulate > Ticks Enabled (Ctrl+K) runs it continuously, at the speed set in
     Simulate > Tick Frequency (256 Hz - 1 kHz is comfortable).
  5. Watch DISPLAY: 01 = ready. Set DOOR_CLOSED=1, choose MODE, then poke START=1.

4. CLOCK / RESET SET-UP
-----------------------
* One rising-edge clock (CLK, high 1 tick / low 1 tick). There are no gated clocks; all conditional updates
  use register enables.
* RESET is active high and asynchronous (it drives the CLR input of every pipeline, I/O, timer and safety
  register). It gives PC=0, all pipeline valid bits 0, HALTED=0, all actuator requests 0, DISPLAY=0,
  timer COUNT/LIMIT/EN/MATCH=0 and TRIP=0. RAM and R0-R7 are not cleared; the program initialises them.
* The timer and the safety latch are clocked every cycle, also when the CPU is stalled or halted.

5. MODE / SENSOR STIMULATION
----------------------------
Input pins (poke a bit to toggle it; multi-bit pins show MSB on the left):
  START (1)  DOOR_CLOSED (1)  MODE (2)  WATER_LEVEL (8)  TEMP (8)  DRUM_RPM (8)
  MODE[0]=0 -> NORMAL: fill to >= 100, wash 64 ticks, spin 32 ticks, drain to <= 10
  MODE[0]=1 -> HEAVY : fill to >= 160, wash 96 ticks, spin 48 ticks, drain to <= 10
  MODE is read once, when START is accepted; later changes have no effect on the running cycle.
Change inputs only while the clock is low (just after a rising edge). Inputs are sampled at the rising edge that ends the MEM stage of an LD.
Useful WATER_LEVEL values: 99=0110 0011, 102=0110 0110, 159=1001 1111, 162=1010 0010, 11=0000 1011, 4=0000 0100.
Outputs: VALVE_IN HEATER MOTOR_EN MOTOR_DIR PUMP_OUT DOOR_LOCK BUZZER (CPU requests), MOTOR_EN_ACTUAL
(safety-gated physical output), TRIP, DISPLAY, TIMER_COUNT, TIMER_MATCH, and a pipeline monitor
(PC, stage PCs + valid bits, STALL, FLUSH, HALTED, FWD_A/FWD_B, WB write port, data-bus write).

Quick check: reset, run the clock, then set DOOR_CLOSED=1, MODE=00, START=1.
  -> DOOR_LOCK=1, DISPLAY 02 then 03, VALVE_IN=1. Set START=0.
  -> WATER_LEVEL=99: valve stays on. WATER_LEVEL=102: valve off, DISPLAY 04, MOTOR_DIR alternates.
  -> after TIMER_MATCH: DISPLAY 05, PUMP_OUT=1. WATER_LEVEL=11: still pumping. WATER_LEVEL=4: DISPLAY 06 (spin).
  -> after the second MATCH: DISPLAY 07, then (DRUM_RPM=0) DISPLAY 08, BUZZER=1, DOOR_LOCK=0.

6. TEST INSTRUCTIONS
--------------------
GUI: open any tests/tN_*.circ, then enable ticks or step with Ctrl+T. These benches need no poking: reset, inputs and the water/drum plant are generated internally. Compare the monitor pins with the tables in pipeline_traces.pdf and validation.pdf.
  t1_hazards       8.1 ALU forwarding, 8.2 load-use (1 stall), 8.3 youngest-writer store data, HALT
  t2_branch_halt   8.4 taken branch kills wrong-path actuator store, wrong-path HALTs ignored
  t3_ram_reserved  RAM store/load, reserved/unimplemented/read-only addresses isolated
  t4_timer         count, sticky MATCH, clear/re-arm, no retroactive MATCH, wrap-around, ticks while stalled/halted
  t5_safety        door opens with motor on -> immediate cut-off, TRIP latch, no auto restart, explicit re-arm
  t6_wash_e2e      full wash, NORMAL then HEAVY, overshoot 99->102 and 159->162, drain, spin, completion
Command line (all six, compared with the expected output):
  sh tests/run_logisim_tests.sh /path/to/logisim-generic-2.7.1.jar
or for one bench:
  java -jar logisim-generic-2.7.1.jar tests/t1_hazards.circ -tty table
The column order is listed in RUNNING_IN_LOGISIM.md.

7. REBUILDING (optional)
------------------------
  python3 tools/design.py        regenerate washing_pipeline.circ, program.hex and tests/*.circ
  python3 tools/make_reports.py  re-run all checks, rewrite tests/expected and latex/generated
  cd latex && make               build the PDFs
